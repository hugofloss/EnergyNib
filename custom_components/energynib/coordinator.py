"""Fetch heat usage and import it as long-term statistics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from .api import EnergyFlipAuthError, EnergyFlipClient, EnergyFlipError, HeatPoint
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_RESOLUTION,
    DEFAULT_BACKFILL_DAYS,
    DETECT_WINDOW,
    DOMAIN,
    FETCH_CHUNK,
    REFETCH_WINDOW,
    RESOLUTION_DAY,
    RESOLUTION_HOUR,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Everything is stored in GJ, the unit EnergyFlip shows for heat.
TO_GJ = {"GJ": 1.0, "MJ": 0.001, "kWh": 0.0036, "MWh": 3.6}


@dataclass
class HeatData:
    """Summary exposed to the sensors."""

    last_timestamp: datetime | None
    last_day_usage: float | None


def _metadata(statistic_id: str, name: str) -> StatisticMetaData:
    meta: dict = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": UnitOfEnergy.GIGA_JOULE,
    }
    # The metadata schema gained fields over time; fill in what this HA version knows.
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        meta["mean_type"] = StatisticMeanType.NONE
    except ImportError:
        meta["has_mean"] = False
    try:
        from homeassistant.util.unit_conversion import EnergyConverter

        meta["unit_class"] = EnergyConverter.UNIT_CLASS
    except (ImportError, AttributeError):
        pass
    return meta  # type: ignore[return-value]


class EnergyFlipHeatCoordinator(DataUpdateCoordinator[HeatData]):
    """Polls EnergyFlip every hour and backfills the statistics."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: EnergyFlipClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        # Options this instance was set up with; the update listener reloads only when they change.
        self.options = dict(entry.options)

    @property
    def statistic_id(self) -> str:
        return f"{DOMAIN}:{slugify(str(self.client.customer_id))}_heat"

    @property
    def resolution(self) -> str | None:
        return self.config_entry.data.get(CONF_RESOLUTION)

    async def _async_update_data(self) -> HeatData:
        try:
            if self.client.customer_id is None:
                await self.client.customer_overview()
            if self.resolution is None and not await self._detect_resolution():
                _LOGGER.debug("No heat data available yet")
                return self._summary(None)
            return await self._import_statistics()
        except EnergyFlipAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EnergyFlipError as err:
            raise UpdateFailed(str(err)) from err

    async def _detect_resolution(self) -> bool:
        """Pick hourly data if the meter has it, else daily, and store the choice for good."""
        end = dt_util.now()
        start = end - DETECT_WINDOW
        try:
            hourly = await self.client.heat_history(start, end, RESOLUTION_HOUR)
        except EnergyFlipAuthError:
            raise
        except EnergyFlipError as err:
            # Only a client error means "not supported"; anything else may be transient.
            if err.status is None or not 400 <= err.status < 500:
                raise
            hourly = []
        if hourly:
            resolution = RESOLUTION_HOUR
        elif await self.client.heat_history(start, end, RESOLUTION_DAY):
            resolution = RESOLUTION_DAY
        else:
            return False

        _LOGGER.info("Using heat data resolution %s", resolution)
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_RESOLUTION: resolution}
        )
        return True

    async def _fetch(self, start: datetime, end: datetime) -> list[HeatPoint]:
        """Fetch in chunks; deduplicate per interval in case chunk boundaries overlap."""
        by_start: dict[datetime, HeatPoint] = {}
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + FETCH_CHUNK, end)
            for point in await self.client.heat_history(chunk_start, chunk_end, self.resolution):
                point.start = point.start.replace(minute=0, second=0, microsecond=0)
                by_start[point.start] = point
            chunk_start = chunk_end
        return sorted(by_start.values(), key=lambda p: p.start)

    async def _import_statistics(self) -> HeatData:
        statistic_id = self.statistic_id
        recorder = get_instance(self.hass)
        now = dt_util.now()
        today = dt_util.start_of_local_day()

        last = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        if not last.get(statistic_id):
            days = self.config_entry.options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS)
            start = today - timedelta(days=days)
            base_sum = 0.0
        else:
            last_row = last[statistic_id][0]
            last_start = dt_util.utc_from_timestamp(last_row["start"])
            start = min(last_start + timedelta(hours=1), now - REFETCH_WINDOW)
            start = start.replace(minute=0, second=0, microsecond=0)
            # Sum of everything before `start`, so re-imported hours stay consistent.
            # Look back a week: with daily data only one row per day exists.
            before = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start - timedelta(days=7),
                start,
                {statistic_id},
                "hour",
                None,
                {"sum"},
            )
            rows = before.get(statistic_id)
            if rows and rows[-1].get("sum") is not None:
                base_sum = rows[-1]["sum"]
            else:
                start = last_start + timedelta(hours=1)
                base_sum = last_row["sum"] or 0.0

        points = [p for p in await self._fetch(start, now) if p.start >= start]
        if not points:
            _LOGGER.debug("No new heat data since %s", start)
            return self._summary(None)

        statistics: list[StatisticData] = []
        running = base_sum
        for point in points:
            factor = TO_GJ.get(point.unit)
            if factor is None:
                raise UpdateFailed(f"Unknown heat unit {point.unit!r}")
            running += point.value * factor
            statistics.append(
                StatisticData(
                    start=point.start,
                    state=point.value * factor,
                    sum=running,
                )
            )

        _LOGGER.debug(
            "Importing %d heat statistics (%s .. %s)",
            len(statistics),
            statistics[0]["start"],
            statistics[-1]["start"],
        )
        async_add_external_statistics(
            self.hass, _metadata(statistic_id, "EnergyFlip warmteverbruik"), statistics
        )
        return self._summary(points)

    def _summary(self, points: list[HeatPoint] | None) -> HeatData:
        if not points:
            return self.data or HeatData(last_timestamp=None, last_day_usage=None)
        last_ts = points[-1].start
        last_day = dt_util.as_local(last_ts).date()
        usage = sum(
            p.value * TO_GJ.get(p.unit, 1.0)
            for p in points
            if dt_util.as_local(p.start).date() == last_day
        )
        return HeatData(last_timestamp=last_ts, last_day_usage=round(usage, 4))
