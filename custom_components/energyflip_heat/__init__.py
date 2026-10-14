"""EnergyFlip Warmte: heat usage from EnergyFlip in the Home Assistant energy dashboard."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EnergyFlipClient
from .coordinator import EnergyFlipHeatCoordinator

PLATFORMS = [Platform.SENSOR]

type EnergyFlipHeatConfigEntry = ConfigEntry[EnergyFlipHeatCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyFlipHeatConfigEntry) -> bool:
    client = EnergyFlipClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = EnergyFlipHeatCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: EnergyFlipHeatConfigEntry) -> None:
    # Data updates (stored resolution, reauth) must not trigger a reload; reauth reloads itself.
    if dict(entry.options) != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EnergyFlipHeatConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
