"""Informational sensors. The energy dashboard uses the imported statistic, not these."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyFlipHeatConfigEntry
from .const import DOMAIN
from .coordinator import EnergyFlipHeatCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyFlipHeatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([LastDayUsageSensor(coordinator), LastMeasurementSensor(coordinator)])


class _Base(CoordinatorEntity[EnergyFlipHeatCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnergyFlipHeatCoordinator, key: str) -> None:
        super().__init__(coordinator)
        customer_id = coordinator.client.customer_id
        self._attr_unique_id = f"{customer_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(customer_id))},
            name="EnergyFlip warmte",
            manufacturer="EnergyFlip",
            entry_type=DeviceEntryType.SERVICE,
        )


class LastDayUsageSensor(_Base):
    """Heat used on the most recent day with data.

    Deliberately without state_class: the long-term statistic is imported
    separately with correct timestamps.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.GIGA_JOULE
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: EnergyFlipHeatCoordinator) -> None:
        super().__init__(coordinator, "last_day_usage")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.last_day_usage if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"statistic_id": self.coordinator.statistic_id}


class LastMeasurementSensor(_Base):
    """Start of the most recent interval EnergyFlip has data for."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EnergyFlipHeatCoordinator) -> None:
        super().__init__(coordinator, "last_measurement")

    @property
    def native_value(self):
        return self.coordinator.data.last_timestamp if self.coordinator.data else None
