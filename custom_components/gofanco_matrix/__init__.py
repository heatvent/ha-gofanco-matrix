"""gofanco Matrix44-HDBT 4x4 HDMI matrix — control over TCP (built-in network module) or RS-232."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from . import protocol
from .const import DOMAIN, PLATFORMS
from .coordinator import MatrixCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MatrixConfigEntry = ConfigEntry[MatrixCoordinator]

ATTR_ENTRY = "config_entry_id"
ATTR_COMMAND = "command"
ATTR_OUTPUT = "output"
ATTR_INPUT = "input"
ATTR_PRESET = "preset"
ATTR_EDID = "edid"
ATTR_MODE = "mode"
ATTR_KEY = "key"
ATTR_DEVICE_TYPE = "device_type"
ATTR_CONFIRM = "confirm"
ATTR_ON = "on"
ATTR_RECEIVER = "receiver"

_ENTRY = {vol.Optional(ATTR_ENTRY): cv.string}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MatrixConfigEntry) -> bool:
    coordinator = MatrixCoordinator(hass, entry)
    try:
        await coordinator.async_start()
    except (OSError, TimeoutError) as err:
        await coordinator.connection.stop()
        raise ConfigEntryNotReady(
            f"Cannot connect to {coordinator.connection.description}: {err}"
        ) from err
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await coordinator.async_shutdown()
        raise
    entry.runtime_data = coordinator

    @callback
    def _sync_device() -> None:
        """Fill in firmware/model once the matrix has reported them."""
        state = coordinator.state
        registry = dr.async_get(hass)
        device = registry.async_get_device(identifiers={coordinator.device_identifier()})
        if device is None or not state.firmware:
            return
        if device.sw_version != state.firmware or (
            state.model_name and device.model != state.model_name
        ):
            registry.async_update_device(
                device.id,
                sw_version=state.firmware,
                model=state.model_name or device.model,
                hw_version=f"CPLD {state.cpld}" if state.cpld else device.hw_version,
            )

    entry.async_on_unload(coordinator.async_add_listener(_sync_device))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MatrixConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


# ------------------------------------------------------------------ services


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> MatrixCoordinator:
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    wanted = call.data.get(ATTR_ENTRY)
    if wanted:
        loaded = [entry for entry in loaded if entry.entry_id == wanted]
    if not loaded:
        raise ServiceValidationError("No gofanco matrix is loaded")
    if len(loaded) > 1:
        raise ServiceValidationError(
            "More than one gofanco matrix is configured; set config_entry_id"
        )
    return loaded[0].runtime_data


def _build(builder, *args):
    try:
        return builder(*args)
    except protocol.CommandError as err:
        raise ServiceValidationError(str(err)) from err


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "send_command"):
        return

    async def send_command(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        try:
            command = protocol.normalize(call.data[ATTR_COMMAND])
        except protocol.CommandError as err:
            raise ServiceValidationError(str(err)) from err
        lines = await coordinator.async_send_collect(command)
        return {"command": command, "reply": lines}

    async def set_route(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        output, input_ = call.data[ATTR_OUTPUT], call.data[ATTR_INPUT]
        _build(protocol.cmd_route, output, input_)
        await coordinator.async_route(output, input_)

    async def simple(call: ServiceCall, builder, *keys, wake: bool = True) -> None:
        coordinator = _coordinator(hass, call)
        command = _build(builder, *(call.data[k] for k in keys))
        await coordinator.async_command(command, wake=wake)

    async def recall_preset(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_preset_recall, ATTR_PRESET)

    async def save_preset(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_preset_save, ATTR_PRESET)

    async def set_hdcp(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_hdcp, ATTR_OUTPUT, ATTR_MODE)

    async def set_edid(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_edid_builtin, ATTR_INPUT, ATTR_EDID)

    async def copy_edid(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_edid_copy, ATTR_OUTPUT, ATTR_INPUT)

    async def restore_default_edid(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        await coordinator.async_command(protocol.cmd_edid_default())

    async def set_poc(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_poc, ATTR_RECEIVER, ATTR_ON)

    async def set_hdmi_5v(call: ServiceCall) -> None:
        await simple(call, protocol.cmd_hdmi_5v, ATTR_OUTPUT, ATTR_ON)

    async def cec_source(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        command = _build(
            protocol.cmd_cec_source,
            call.data[ATTR_INPUT],
            call.data[ATTR_KEY],
            call.data[ATTR_DEVICE_TYPE],
        )
        await coordinator.async_command(command)

    async def cec_display(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        command = _build(
            protocol.cmd_cec_display,
            call.data[ATTR_OUTPUT],
            call.data[ATTR_KEY],
            call.data[ATTR_DEVICE_TYPE],
        )
        await coordinator.async_command(command)

    async def factory_reset(call: ServiceCall) -> None:
        if not call.data.get(ATTR_CONFIRM):
            raise ServiceValidationError("Set confirm: true to factory reset the matrix")
        coordinator = _coordinator(hass, call)
        _LOGGER.warning("Sending factory reset (RST.) to %s", coordinator.connection.description)
        await coordinator.async_command(protocol.FACTORY_RESET)

    output_all = vol.All(vol.Coerce(int), vol.Range(0, protocol.OUTPUTS))
    hdmi_output = vol.All(vol.Coerce(int), vol.In([0, *protocol.HDMI_5V_OUTPUTS]))
    input_all = vol.All(vol.Coerce(int), vol.Range(0, protocol.INPUTS))
    services = {
        "send_command": (
            send_command,
            {vol.Required(ATTR_COMMAND): cv.string},
            SupportsResponse.OPTIONAL,
        ),
        "set_route": (
            set_route,
            {
                vol.Required(ATTR_OUTPUT): vol.All(vol.Coerce(int), vol.Range(0, protocol.ROUTABLE_OUTPUTS)),
                vol.Required(ATTR_INPUT): vol.All(vol.Coerce(int), vol.Range(1, protocol.INPUTS)),
            },
            SupportsResponse.NONE,
        ),
        "recall_preset": (recall_preset, {vol.Required(ATTR_PRESET): vol.Coerce(int)}, SupportsResponse.NONE),
        "save_preset": (save_preset, {vol.Required(ATTR_PRESET): vol.Coerce(int)}, SupportsResponse.NONE),
        "set_hdcp": (
            set_hdcp,
            {vol.Required(ATTR_OUTPUT): output_all, vol.Required(ATTR_MODE): vol.In(list(protocol.HDCP_MODES))},
            SupportsResponse.NONE,
        ),
        "set_edid": (
            set_edid,
            {vol.Required(ATTR_INPUT): input_all, vol.Required(ATTR_EDID): vol.Coerce(int)},
            SupportsResponse.NONE,
        ),
        "copy_edid": (
            copy_edid,
            {vol.Required(ATTR_OUTPUT): output_all, vol.Required(ATTR_INPUT): input_all},
            SupportsResponse.NONE,
        ),
        "restore_default_edid": (restore_default_edid, {}, SupportsResponse.NONE),
        "set_poc": (
            set_poc,
            {
                vol.Required(ATTR_RECEIVER): vol.All(vol.Coerce(int), vol.Range(0, protocol.RECEIVERS)),
                vol.Required(ATTR_ON): cv.boolean,
            },
            SupportsResponse.NONE,
        ),
        "set_hdmi_5v": (
            set_hdmi_5v,
            {vol.Required(ATTR_OUTPUT): hdmi_output, vol.Required(ATTR_ON): cv.boolean},
            SupportsResponse.NONE,
        ),
        "cec_source": (
            cec_source,
            {
                vol.Required(ATTR_INPUT): input_all,
                vol.Required(ATTR_KEY): vol.In(list(protocol.CEC_SOURCE_KEYS)),
                vol.Optional(ATTR_DEVICE_TYPE, default="04"): vol.Match(r"^[0-9A-Fa-f]{2}$"),
            },
            SupportsResponse.NONE,
        ),
        "cec_display": (
            cec_display,
            {
                vol.Required(ATTR_OUTPUT): hdmi_output,
                vol.Required(ATTR_KEY): vol.In(
                    [*protocol.CEC_DISPLAY_POWER, *protocol.CEC_DISPLAY_KEYS]
                ),
                vol.Optional(ATTR_DEVICE_TYPE, default="40"): vol.Match(r"^[0-9A-Fa-f]{2}$"),
            },
            SupportsResponse.NONE,
        ),
        "factory_reset": (factory_reset, {vol.Required(ATTR_CONFIRM): cv.boolean}, SupportsResponse.NONE),
    }
    for name, (handler, schema, supports) in services.items():
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=vol.Schema({**_ENTRY, **schema}),
            supports_response=supports,
        )
