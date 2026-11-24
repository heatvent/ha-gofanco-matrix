"""Base entity for the matrix device."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MANUFACTURER
from .coordinator import MatrixCoordinator


class MatrixEntity(CoordinatorEntity[MatrixCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MatrixCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        state = coordinator.state
        self._attr_device_info = DeviceInfo(
            identifiers={coordinator.device_identifier()},
            name=coordinator.entry.title,
            manufacturer=MANUFACTURER,
            model=state.model_name or "Matrix44-HDBT",
            model_id="G4-0064B",
            sw_version=state.firmware,
            hw_version=f"CPLD {state.cpld}" if state.cpld else None,
            configuration_url=(
                None
                if coordinator.is_serial
                else f"http://{coordinator.entry.data.get('host')}/"
            ),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.connection.connected and super().available


class MatrixAwakeEntity(MatrixEntity):
    """Settings the matrix only reports while it is on (not in standby)."""

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.state.power is not False
