"""Minimal async client for the (undocumented) EnergyFlip / Aurum Europe API.

The endpoints are the ones used by the web app at https://web.energyflip.com.
This module has no Home Assistant dependencies so it can also be used from
scripts/probe.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import API_URL, OAUTH_CLIENT_ID, OAUTH_SCOPE, SOURCE_TYPE_HEAT

TOKEN_PATH = "/oauth2/v1/token"
CUSTOMER_OVERVIEW_PATH = "/user/v3/customers/overview"
CUMULATIVE_HISTORY_PATH = "/user/v4/customers/{customer_id}/measurements/cumulativeHistory"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class EnergyFlipError(Exception):
    """Generic API error."""


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
        async with self._session.post(
            self._api_url + TOKEN_PATH,
            data=data,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status in (400, 401, 403):
                raise EnergyFlipAuthError(f"Login refused ({resp.status}): {await resp.text()}")
            if resp.status >= 300:
                raise EnergyFlipError(f"Token request failed ({resp.status}): {await resp.text()}")
            body = await resp.json(content_type=None)

        self._access_token = body["access_token"]
        self._refresh_token = body.get("refresh_token", self._refresh_token)
        # Renew a minute early to avoid racing the expiry.
        self._expires_at = time.monotonic() + float(body.get("expires_in", 3600)) - 60

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
                return await self._get(path, params, retry=False)
            if resp.status == 401:
                raise EnergyFlipAuthError(await resp.text())
            if resp.status >= 300:
                raise EnergyFlipError(f"GET {path} failed ({resp.status}): {await resp.text()}")
            return await resp.json(content_type=None)

    async def customer_overview(self) -> dict[str, Any]:
        """Fetch the customer overview and remember customer id and sources."""
        body = await self._get(CUSTOMER_OVERVIEW_PATH)
        summary = body["data"]["customerSummary"]
        self.customer_id = summary["sessionIdentifiers"]["customerId"]
        self.sources = {s["type"]: s["source"] for s in summary.get("sources", [])}
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
            CUMULATIVE_HISTORY_PATH.format(customer_id=self.customer_id),
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
        body = await self.cumulative_history_raw(SOURCE_TYPE_HEAT, resolution, start, end)
        values = (body.get("data") or {}).get("cumulativeHistory", {}).get("values") or []
        points: list[HeatPoint] = []
        for item in values:
            heat = item.get(SOURCE_TYPE_HEAT) or {}
            if heat.get("value") is None:
                continue
            points.append(
                HeatPoint(
                    start=datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")),
                    value=float(heat["value"]),
                    unit=heat.get("unit") or "GJ",
                )
            )
        points.sort(key=lambda p: p.start)
        return points
