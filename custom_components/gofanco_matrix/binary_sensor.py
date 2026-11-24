"""Signal/link status per input and output (from STA.'s LINK/TMDS table)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import protocol
from .coordinator import MatrixCoordinator
from .entity import MatrixAwakeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MatrixCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for i in range(1, protocol.INPUTS + 1):
        name = coordinator.input_names[i - 1]
        entities.append(LinkSensor(coordinator, f"input_{i}_link", f"{name} connected", "input_link", i))
        entities.append(LinkSensor(coordinator, f"input_{i}_signal", f"{name} signal", "input_tmds", i))
    for o in range(1, protocol.OUTPUTS + 1):
        entities.append(
            LinkSensor(coordinator, f"output_{o}_link", f"{coordinator.output_label(o)} connected", "output_link", o)
        )
    async_add_entities(entities)


class LinkSensor(MatrixAwakeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, name, field, port) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._field = field
        self._port = port

    @property
    def is_on(self) -> bool | None:
        return getattr(self.coordinator.state, self._field).get(self._port)
