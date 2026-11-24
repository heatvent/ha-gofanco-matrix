"""Routing and other one-of-many settings."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import protocol
from .coordinator import MatrixCoordinator
from .entity import MatrixEntity

HDCP_OPTIONS = {"on": "HDCP on", "off": "HDCP off", "match": "Match display", "bypass": "Bypass"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MatrixCoordinator = entry.runtime_data
    entities: list[SelectEntity] = [
        OutputSourceSelect(coordinator, output)
        for output in range(1, protocol.ROUTABLE_OUTPUTS + 1)
    ]
    entities.append(AudioSourceSelect(coordinator))
    entities += [HdcpSelect(coordinator, output) for output in range(1, protocol.OUTPUTS + 1)]
    entities += [
        IrRouteSelect(coordinator, receiver) for receiver in range(1, protocol.RECEIVERS + 1)
    ]
    async_add_entities(entities)


class OutputSourceSelect(MatrixEntity, SelectEntity):
    """Which input an output shows. This is the matrix control."""

    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator: MatrixCoordinator, output: int) -> None:
        super().__init__(coordinator, f"output_{output}_source")
        self._output = output
        self._attr_name = f"{coordinator.output_names[output - 1]} source"

    @property
    def options(self) -> list[str]:
        return self.coordinator.input_names

    @property
    def current_option(self) -> str | None:
        input_ = self.coordinator.state.routes.get(self._output)
        if not input_ or input_ > len(self.options):
            return None
        return self.options[input_ - 1]

    @property
    def extra_state_attributes(self) -> dict:
        return {"output": self._output, "input": self.coordinator.state.routes.get(self._output)}

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_route(self._output, self.options.index(option) + 1)


class AudioSourceSelect(MatrixEntity, SelectEntity):
    """The de-embedded audio out follows one video output."""

    _attr_icon = "mdi:speaker"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MatrixCoordinator) -> None:
        super().__init__(coordinator, "audio_out_source")
        self._attr_name = "Audio out follows"

    @property
    def options(self) -> list[str]:
        return self.coordinator.output_names

    @property
    def current_option(self) -> str | None:
        output = self.coordinator.state.audio_source
        return self.options[output - 1] if output and output <= len(self.options) else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_command(
            protocol.cmd_audio_source(self.options.index(option) + 1)
        )


class HdcpSelect(MatrixEntity, SelectEntity):
    _attr_icon = "mdi:shield-key"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: MatrixCoordinator, output: int) -> None:
        super().__init__(coordinator, f"output_{output}_hdcp")
        self._output = output
        self._attr_name = f"{coordinator.output_label(output)} HDCP"
        self._attr_options = list(HDCP_OPTIONS.values())

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.state.hdcp.get(self._output)
        return HDCP_OPTIONS.get(mode) if mode else None

    async def async_select_option(self, option: str) -> None:
        mode = next(key for key, label in HDCP_OPTIONS.items() if label == option)
        await self.coordinator.async_command(protocol.cmd_hdcp(self._output, mode))


class IrRouteSelect(MatrixEntity, SelectEntity):
    """Where an HDBaseT receiver's IR eye is sent (only used when IR follows video is off)."""

    _attr_icon = "mdi:remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: MatrixCoordinator, receiver: int) -> None:
        super().__init__(coordinator, f"receiver_{receiver}_ir_route")
        self._receiver = receiver
        self._attr_name = f"Receiver {receiver} IR to"

    @property
    def options(self) -> list[str]:
        return [f"{name} IR out" for name in self.coordinator.output_names]

    @property
    def current_option(self) -> str | None:
        local = self.coordinator.state.ir_routes.get(self._receiver)
        return self.options[local - 1] if local and local <= len(self.options) else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_command(
            protocol.cmd_ir_route(self.options.index(option) + 1, self._receiver)
        )
