"""Temperature and diagnostic text sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import protocol
from .coordinator import MatrixCoordinator
from .entity import MatrixEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MatrixCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        TemperatureSensor(coordinator),
        TextSensor(coordinator, "firmware", "Firmware", "mdi:chip", lambda s: s.firmware),
        TextSensor(coordinator, "gui_ip", "Matrix stored IP", "mdi:ip", lambda s: s.gui_ip),
        TextSensor(
            coordinator,
            "rs232_baud",
            "RS-232 baud rate",
            "mdi:serial-port",
            lambda s: str(s.baud_rate) if s.baud_rate else None,
        ),
    ]
    entities += [
        TextSensor(
            coordinator,
            f"input_{i}_edid",
            f"{coordinator.input_names[i - 1]} EDID",
            "mdi:monitor-screenshot",
            lambda s, i=i: s.edid.get(i),
        )
        for i in range(1, protocol.INPUTS + 1)
    ]
    async_add_entities(entities)


class TemperatureSensor(MatrixEntity, SensorEntity):
    _attr_name = "Board temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MatrixCoordinator) -> None:
        super().__init__(coordinator, "temperature")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.state.temperature


class TextSensor(MatrixEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, name, icon, read) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_icon = icon
        self._read = read
        if key.endswith("_edid") or key == "rs232_baud" or key == "gui_ip":
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | None:
        return self._read(self.coordinator.state)
