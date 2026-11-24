"""Coordinator: owns the connection, applies pushed lines, polls STA. as a safety net."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import protocol
from .connection import (
    TRANSPORT_SERIAL,
    MatrixConnection,
    serial_opener,
    tcp_opener,
)
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
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TCP_PORT,
    DOMAIN,
    POWER_ON_SETTLE,
)

_LOGGER = logging.getLogger(__name__)


def build_connection(data: dict) -> MatrixConnection:
    if data.get(CONF_TRANSPORT) == TRANSPORT_SERIAL:
        device = data[CONF_SERIAL_PORT]
        baud = int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
        return MatrixConnection(serial_opener(device, baud), f"{device} @ {baud}")
    host = data[CONF_HOST]
    port = int(data.get(CONF_PORT, DEFAULT_TCP_PORT))
    return MatrixConnection(tcp_opener(host, port), f"{host}:{port}")


def split_names(raw: str | None, count: int, prefix: str) -> list[str]:
    parts = [p.strip() for p in (raw or "").split(",")]
    return [
        (parts[i] if i < len(parts) and parts[i] else f"{prefix} {i + 1}") for i in range(count)
    ]


class MatrixCoordinator(DataUpdateCoordinator[protocol.MatrixState]):
    """State comes mostly from pushed lines; the poll catches anything missed."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        poll = int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=poll),
        )
        self.entry = entry
        self.connection = build_connection(dict(entry.data))
        self.parser = protocol.Parser()
        self._unsubs = [
            self.connection.add_line_listener(self._on_line),
            self.connection.add_state_listener(self._on_connection_state),
        ]
        self._push_scheduled = False
        self.last_reply: list[str] = []

    # ------------------------------------------------------------ properties

    @property
    def state(self) -> protocol.MatrixState:
        return self.parser.state

    @property
    def input_names(self) -> list[str]:
        return split_names(self.entry.options.get(CONF_INPUT_NAMES), protocol.INPUTS, "Input")

    @property
    def output_names(self) -> list[str]:
        return split_names(
            self.entry.options.get(CONF_OUTPUT_NAMES), protocol.ROUTABLE_OUTPUTS, "Output"
        )

    @property
    def auto_power_on(self) -> bool:
        return bool(self.entry.options.get(CONF_AUTO_POWER_ON, DEFAULT_AUTO_POWER_ON))

    @property
    def is_serial(self) -> bool:
        return self.entry.data.get(CONF_TRANSPORT) == TRANSPORT_SERIAL

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        await self.connection.connect_once()
        await self.connection.start()

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self.connection.stop()
        await super().async_shutdown()

    # ------------------------------------------------------------ push path

    @callback
    def _on_line(self, line: str) -> None:
        if self.parser.feed(line) and not self._push_scheduled:
            # A status burst is ~40 lines; publish once after it settles.
            self._push_scheduled = True
            self.hass.loop.call_later(0.2, self._publish)

    @callback
    def _publish(self) -> None:
        self._push_scheduled = False
        self.async_set_updated_data(self.state)

    @callback
    def _on_connection_state(self, connected: bool) -> None:
        if connected:
            self.hass.async_create_task(self.async_request_refresh())
        else:
            self.async_update_listeners()

    # ------------------------------------------------------------ poll path

    async def _async_update_data(self) -> protocol.MatrixState:
        if not self.connection.connected:
            if not await self.connection.wait_connected(5):
                raise UpdateFailed(f"Not connected to {self.connection.description}")
        try:
            reply = await self.connection.send(protocol.STATUS_ALL, collect=True)
        except ConnectionError as err:
            raise UpdateFailed(str(err)) from err
        if not protocol.reply_shows_awake(reply):
            # In standby the matrix answers STA. with nothing, or only its header and
            # model lines - never the power/routing lines. Only PowerON. works then.
            if self.state.power is not False:
                self.state.power = False
        elif self.state.model_name is None or self.state.firmware is None:
            for command in protocol.STATUS_INFO:
                await self.connection.send(command, collect=True)
        return self.state

    # ------------------------------------------------------------ commands

    async def async_send(self, command: str) -> None:
        try:
            await self.connection.send(command)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_send_collect(self, command: str) -> list[str]:
        try:
            self.last_reply = await self.connection.send(command, collect=True)
        except ConnectionError as err:
            raise HomeAssistantError(str(err)) from err
        return self.last_reply

    async def async_ensure_on(self) -> None:
        """Wake the matrix before a command it would ignore in standby."""
        if self.state.power is False and self.auto_power_on:
            await self.async_send(protocol.cmd_power(True))
            await asyncio.sleep(POWER_ON_SETTLE)
            self.hass.async_create_task(self.async_request_refresh())

    async def async_set_power(self, on: bool) -> None:
        await self.async_send(protocol.cmd_power(on))
        self.state.power = on
        self.async_set_updated_data(self.state)
        if on:
            # Standby hides temperature, links and settings; read them once awake.
            self.hass.async_create_task(self._async_refresh_after_wake())

    async def _async_refresh_after_wake(self) -> None:
        await asyncio.sleep(POWER_ON_SETTLE)
        await self.async_request_refresh()

    async def async_route(self, output: int, input_: int) -> None:
        command = protocol.cmd_route(output, input_)
        await self.async_ensure_on()
        await self.async_send(command)

    async def async_command(self, command: str, *, wake: bool = True) -> None:
        """Send a setting command; the matrix confirms with a pushed line."""
        if wake:
            await self.async_ensure_on()
        await self.async_send(command)

    def output_label(self, output: int) -> str:
        if output <= protocol.ROUTABLE_OUTPUTS:
            return self.output_names[output - 1]
        return f"{self.output_names[2]} loop-out"

    def device_identifier(self) -> tuple[str, str]:
        return (DOMAIN, self.entry.entry_id)
