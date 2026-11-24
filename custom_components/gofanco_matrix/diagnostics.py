"""Diagnostics download: connection, parsed state and the last raw reply."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import MatrixCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: MatrixCoordinator = entry.runtime_data
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "connection": coordinator.connection.diagnostics(),
        "state": asdict(coordinator.state),
        "last_send_command_reply": coordinator.last_reply,
    }
