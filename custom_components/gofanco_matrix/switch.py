"""Power and on/off settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import protocol
from .coordinator import MatrixCoordinator
from .entity import MatrixEntity


@dataclass(frozen=True)
class SwitchSpec:
    key: str
    name: str
    icon: str
    read: Callable[[protocol.MatrixState], bool | None]
    command: Callable[[bool], str]
    category: EntityCategory | None = EntityCategory.CONFIG
    enabled: bool = True


def _specs(coordinator: MatrixCoordinator) -> list[SwitchSpec]:
    specs = [
        SwitchSpec(
            "front_panel_lock",
            "Front panel lock",
            "mdi:lock",
            lambda s: s.front_panel_locked,
            protocol.cmd_lock,
        ),
        SwitchSpec(
            "ir_follow_video",
            "IR follows video",
            "mdi:remote",
            lambda s: s.ir_follow_video,
            protocol.cmd_ir_follow_video,
        ),
    ]
    for receiver in range(1, protocol.RECEIVERS + 1):
        name = coordinator.output_names[receiver - 1]
        specs.append(
            SwitchSpec(
                f"receiver_{receiver}_poc",
                f"{name} receiver power (PoC)",
                "mdi:power-plug",
                lambda s, r=receiver: s.poc.get(r),
                lambda on, r=receiver: protocol.cmd_poc(r, on),
            )
        )
        specs.append(
            SwitchSpec(
                f"receiver_{receiver}_ir_controls_matrix",
                f"{name} receiver IR controls matrix",
                "mdi:remote-tv",
                lambda s, r=receiver: s.receiver_ir_controls_matrix.get(r),
                lambda on, r=receiver: protocol.cmd_receiver_ir_controls_matrix(r, on),
                enabled=False,
            )
        )
    for output in protocol.HDMI_5V_OUTPUTS:
        specs.append(
            SwitchSpec(
                f"output_{output}_hdmi_5v",
                f"{coordinator.output_label(output)} HDMI 5V",
                "mdi:flash",
                lambda s, o=output: s.hdmi_5v.get(o),
                lambda on, o=output: protocol.cmd_hdmi_5v(o, on),
                enabled=False,
            )
        )
    return specs


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MatrixCoordinator = entry.runtime_data
    entities: list[SwitchEntity] = [PowerSwitch(coordinator)]
    entities += [SettingSwitch(coordinator, spec) for spec in _specs(coordinator)]
    async_add_entities(entities)


class PowerSwitch(MatrixEntity, SwitchEntity):
    """PowerON. / PowerOFF. In standby the matrix ignores everything but PowerON."""

    _attr_icon = "mdi:power"
    _attr_name = "Power"

    def __init__(self, coordinator: MatrixCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.state.power

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_power(False)


class SettingSwitch(MatrixEntity, SwitchEntity):
    def __init__(self, coordinator: MatrixCoordinator, spec: SwitchSpec) -> None:
        super().__init__(coordinator, spec.key)
        self._spec = spec
        self._attr_name = spec.name
        self._attr_icon = spec.icon
        self._attr_entity_category = spec.category
        self._attr_entity_registry_enabled_default = spec.enabled

    @property
    def is_on(self) -> bool | None:
        return self._spec.read(self.coordinator.state)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_command(self._spec.command(True))

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_command(self._spec.command(False))
