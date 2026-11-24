"""Config flow: pick TCP (network module) or serial (RS-232), then names and options."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import protocol
from .connection import TRANSPORT_SERIAL, TRANSPORT_TCP
from .const import (
    CONF_AUTO_POWER_ON,
    CONF_BAUDRATE,
    CONF_INPUT_NAMES,
    CONF_OUTPUT_NAMES,
    CONF_POLL_INTERVAL,
    CONF_SERIAL_PORT,
    CONF_TRANSPORT,
    DEFAULT_AUTO_POWER_ON,
    DEFAULT_BAUDRATE,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TCP_PORT,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .coordinator import build_connection

_LOGGER = logging.getLogger(__name__)


async def _probe(data: dict[str, Any]) -> dict[str, str]:
    """Open the connection and ask for status. Returns errors for the form."""
    connection = build_connection(data)
    try:
        await connection.connect_once()
        # A matrix in standby stays silent, so silence is not an error.
        await connection.send(protocol.STATUS_VIDEO, collect=True)
    except (OSError, TimeoutError, ConnectionError) as err:
        _LOGGER.debug("Probe of %s failed: %s", connection.description, err)
        return {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error probing %s", connection.description)
        return {"base": "unknown"}
    finally:
        await connection.stop()
    return {}


def _unique_id(data: dict[str, Any]) -> str:
    if data[CONF_TRANSPORT] == TRANSPORT_SERIAL:
        return f"serial:{data[CONF_SERIAL_PORT]}"
    return f"tcp:{data[CONF_HOST]}:{int(data[CONF_PORT])}"


async def _serial_ports(hass: HomeAssistant) -> list[str]:
    def _list() -> list[str]:
        try:
            from serial.tools import list_ports  # noqa: PLC0415
        except ImportError:
            return []
        ports = []
        for port in list_ports.comports():
            ports.append(getattr(port, "device", str(port)))
        return sorted(ports)

    return await hass.async_add_executor_job(_list)


def _tcp_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = str
    fields[vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, ""))] = str
    fields[vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_TCP_PORT))] = (
        selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=65535, mode="box"))
    )
    return vol.Schema(fields)


def _serial_schema(defaults: dict[str, Any], ports: list[str], with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = str
    fields[
        vol.Required(CONF_SERIAL_PORT, default=defaults.get(CONF_SERIAL_PORT, ports[0] if ports else ""))
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=ports, custom_value=True, mode="dropdown")
    )
    fields[vol.Required(CONF_BAUDRATE, default=str(defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)))] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(options=[str(b) for b in protocol.BAUD_RATES])
        )
    )
    return vol.Schema(fields)


def _tcp_data(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_TRANSPORT: TRANSPORT_TCP,
        CONF_HOST: user_input[CONF_HOST].strip(),
        CONF_PORT: int(user_input[CONF_PORT]),
    }


def _serial_data(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_TRANSPORT: TRANSPORT_SERIAL,
        CONF_SERIAL_PORT: user_input[CONF_SERIAL_PORT].strip(),
        CONF_BAUDRATE: int(user_input[CONF_BAUDRATE]),
    }


class GofancoMatrixConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GofancoMatrixOptionsFlow()

    # ------------------------------------------------------------ add

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["tcp", "serial"])

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _tcp_data(user_input)
            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()
            errors = await _probe(data)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="tcp", data_schema=_tcp_schema(user_input or {}, True), errors=errors
        )

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _serial_data(user_input)
            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()
            errors = await _probe(data)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        ports = await _serial_ports(self.hass)
        return self.async_show_form(
            step_id="serial",
            data_schema=_serial_schema(user_input or {}, ports, True),
            errors=errors,
        )

    # ------------------------------------------------------------ switch serial <-> IP later

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["reconfigure_tcp", "reconfigure_serial"]
        )

    async def _finish_reconfigure(
        self, data: dict[str, Any], step_id: str, schema: vol.Schema
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        new_id = _unique_id(data)
        for other in self._async_current_entries(include_ignore=False):
            if other.entry_id != entry.entry_id and other.unique_id == new_id:
                return self.async_abort(reason="already_configured")
        errors = await _probe(data)
        if errors:
            return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)
        return self.async_update_reload_and_abort(entry, unique_id=new_id, data=data)

    async def async_step_reconfigure_tcp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._finish_reconfigure(
                _tcp_data(user_input), "reconfigure_tcp", _tcp_schema(user_input, False)
            )
        current = dict(self._get_reconfigure_entry().data)
        defaults = current if current.get(CONF_TRANSPORT) == TRANSPORT_TCP else {}
        return self.async_show_form(
            step_id="reconfigure_tcp", data_schema=_tcp_schema(defaults, False)
        )

    async def async_step_reconfigure_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        ports = await _serial_ports(self.hass)
        if user_input is not None:
            return await self._finish_reconfigure(
                _serial_data(user_input),
                "reconfigure_serial",
                _serial_schema(user_input, ports, False),
            )
        current = dict(self._get_reconfigure_entry().data)
        defaults = current if current.get(CONF_TRANSPORT) == TRANSPORT_SERIAL else {}
        return self.async_show_form(
            step_id="reconfigure_serial", data_schema=_serial_schema(defaults, ports, False)
        )


class GofancoMatrixOptionsFlow(OptionsFlow):
    """Names for inputs/outputs, poll interval, auto power-on."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                CONF_INPUT_NAMES: ",".join(
                    user_input.get(f"input_{i}", "").strip() for i in range(1, protocol.INPUTS + 1)
                ),
                CONF_OUTPUT_NAMES: ",".join(
                    user_input.get(f"output_{o}", "").strip()
                    for o in range(1, protocol.ROUTABLE_OUTPUTS + 1)
                ),
                CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL]),
                CONF_AUTO_POWER_ON: bool(user_input[CONF_AUTO_POWER_ON]),
            }
            return self.async_create_entry(data=options)

        opts = self.config_entry.options
        inputs = (opts.get(CONF_INPUT_NAMES) or "").split(",")
        outputs = (opts.get(CONF_OUTPUT_NAMES) or "").split(",")
        fields: dict = {}
        for i in range(1, protocol.INPUTS + 1):
            fields[vol.Optional(f"input_{i}", default=inputs[i - 1] if i <= len(inputs) else "")] = str
        for o in range(1, protocol.ROUTABLE_OUTPUTS + 1):
            fields[vol.Optional(f"output_{o}", default=outputs[o - 1] if o <= len(outputs) else "")] = str
        fields[
            vol.Required(
                CONF_POLL_INTERVAL, default=opts.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            )
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL, unit_of_measurement="s", mode="box"
            )
        )
        fields[
            vol.Required(
                CONF_AUTO_POWER_ON, default=opts.get(CONF_AUTO_POWER_ON, DEFAULT_AUTO_POWER_ON)
            )
        ] = bool
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
