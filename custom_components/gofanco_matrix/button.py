"""Refresh and preset-recall buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import protocol
from .coordinator import MatrixCoordinator
from .entity import MatrixEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MatrixCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = [RefreshButton(coordinator)]
    entities += [PresetButton(coordinator, p) for p in range(1, protocol.PRESETS + 1)]
    async_add_entities(entities)


class RefreshButton(MatrixEntity, ButtonEntity):
    _attr_name = "Refresh status"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MatrixCoordinator) -> None:
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class PresetButton(MatrixEntity, ButtonEntity):
    _attr_icon = "mdi:playlist-play"

    def __init__(self, coordinator: MatrixCoordinator, preset: int) -> None:
        super().__init__(coordinator, f"preset_{preset}_recall")
        self._preset = preset
        self._attr_name = f"Recall preset {preset}"
        # The front panel and web page use presets 1-6; 7-9 are RS-232 only.
        self._attr_entity_registry_enabled_default = preset <= 6

    async def async_press(self) -> None:
        await self.coordinator.async_command(protocol.cmd_preset_recall(self._preset))
