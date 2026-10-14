"""Minimal async client for the (undocumented) EnergyFlip / Aurum Europe API.

The endpoints are the ones used by the web app at https://web.energyflip.com.
This module has no Home Assistant dependencies so it can also be used from
scripts/probe.py.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from .const import API_URL, OAUTH_CLIENT_ID, OAUTH_SCOPE, SOURCE_TYPE_HEAT

TOKEN_PATH = "/oauth2/v1/token"
CUSTOMER_OVERVIEW_PATH = "/user/v3/customers/overview"
CUMULATIVE_HISTORY_PATH = "/user/v4/customers/{customer_id}/measurements/cumulativeHistory"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The web app parses timestamps without offset as local (Dutch) time.
API_TIMEZONE = ZoneInfo("Europe/Amsterdam")


class EnergyFlipError(Exception):
    """Generic API error. ``status`` is the HTTP status, if there was a response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class EnergyFlipAuthError(EnergyFlipError):
    """Invalid credentials or the session could not be renewed."""


@dataclass
class HeatPoint:
    """Heat usage during one interval starting at ``start``."""

    start: datetime
    value: float
    unit: str


def _iso(dt: datetime) -> str:
    """Format like dayjs().toISOString(), which the web app sends."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _snippet(resp: aiohttp.ClientResponse) -> str:
    """Start of a response body, short enough to log without dumping personal data."""
    text = await resp.text()
    return text[:200] + ("…" if len(text) > 200 else "")


def parse_heat_points(body: dict[str, Any]) -> list[HeatPoint]:
    """Extract heat usage per interval from a cumulativeHistory response, oldest first."""
    try:
        values = (body.get("data") or {}).get("cumulativeHistory", {}).get("values") or []
        points: list[HeatPoint] = []
        for item in values:
            heat = item.get(SOURCE_TYPE_HEAT) or {}
            if heat.get("value") is None:
                continue
            start = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=API_TIMEZONE)
            points.append(
                HeatPoint(start=start, value=float(heat["value"]), unit=heat.get("unit") or "GJ")
            )
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise EnergyFlipError(f"Unexpected history response: {err!r}") from err
    points.sort(key=lambda p: p.start)
    return points


class EnergyFlipClient:
    """Client that logs in with username/password and keeps the session alive."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        api_url: str = API_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._api_url = api_url.rstrip("/")
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0
        self.customer_id: str | None = None
        self.sources: dict[str, str] = {}

    async def _token_request(self, data: dict[str, str]) -> None:
        try:
            async with self._session.post(
                self._api_url + TOKEN_PATH,
                data=data,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise EnergyFlipAuthError(
                        f"Login refused ({resp.status}): {await _snippet(resp)}", resp.status
                    )
                if resp.status >= 300:
                    raise EnergyFlipError(
                        f"Token request failed ({resp.status}): {await _snippet(resp)}", resp.status
                    )
                body = await resp.json(content_type=None)
            access_token = body["access_token"]
            expires_in = float(body.get("expires_in", 3600))
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise EnergyFlipError(f"Token request failed: {err!r}") from err
        except (KeyError, TypeError, ValueError) as err:
            raise EnergyFlipError(f"Unexpected token response: {err!r}") from err

        self._access_token = access_token
        self._refresh_token = body.get("refresh_token", self._refresh_token)
        # Renew a minute early to avoid racing the expiry.
        self._expires_at = time.monotonic() + expires_in - 60

    async def login(self) -> None:
        """Log in with username and password (OAuth2 password grant)."""
        self._access_token = None
        await self._token_request(
            {
                "grant_type": "password",
                "client_id": OAUTH_CLIENT_ID,
                "username": self._username,
                "password": self._password,
                "scope": OAUTH_SCOPE,
            }
        )

    async def _ensure_token(self) -> None:
        if self._access_token and time.monotonic() < self._expires_at:
            return
        if self._refresh_token:
            try:
                await self._token_request(
                    {
                        "grant_type": "refresh_token",
                        "client_id": OAUTH_CLIENT_ID,
                        "refresh_token": self._refresh_token,
                    }
                )
                return
            except EnergyFlipAuthError:
                self._refresh_token = None
        await self.login()

    async def _get(self, path: str, params: dict[str, str] | None = None, retry: bool = True) -> Any:
        await self._ensure_token()
        try:
            async with self._session.get(
                self._api_url + path,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._access_token}",
                },
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 401 and retry:
                    self._access_token = None
                elif resp.status == 401:
                    raise EnergyFlipAuthError(await _snippet(resp), resp.status)
                elif resp.status >= 300:
                    raise EnergyFlipError(
                        f"GET {path} failed ({resp.status}): {await _snippet(resp)}", resp.status
                    )
                else:
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise EnergyFlipError(f"GET {path} failed: {err!r}") from err
        except ValueError as err:
            raise EnergyFlipError(f"GET {path} returned invalid JSON: {err!r}") from err
        return await self._get(path, params, retry=False)

    async def customer_overview(self) -> dict[str, Any]:
        """Fetch the customer overview and remember customer id and sources."""
        body = await self._get(CUSTOMER_OVERVIEW_PATH)
        try:
            summary = body["data"]["customerSummary"]
            customer_id = str(summary["sessionIdentifiers"]["customerId"])
            sources = {s["type"]: s["source"] for s in summary.get("sources", [])}
        except (KeyError, TypeError) as err:
            raise EnergyFlipError(f"Unexpected customer overview: {err!r}") from err
        self.customer_id = customer_id
        self.sources = sources
        return body

    async def cumulative_history_raw(
        self, view: str, resolution: str, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Raw response of the history endpoint used by the web app's graphs.

        resolution: hour1, day1, month1 or year1.
        """
        if self.customer_id is None:
            await self.customer_overview()
        return await self._get(
            CUMULATIVE_HISTORY_PATH.format(customer_id=quote(self.customer_id, safe="")),
            {
                "timeResolution": resolution,
                "startTime": _iso(start),
                "endTime": _iso(end),
                "views": view,
            },
        )

    async def heat_history(
        self, start: datetime, end: datetime, resolution: str = "hour1"
    ) -> list[HeatPoint]:
        """Heat usage per interval between start and end, oldest first."""
        return parse_heat_points(
            await self.cumulative_history_raw(SOURCE_TYPE_HEAT, resolution, start, end)
        )
