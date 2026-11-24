"""Transport for the matrix: TCP (the built-in network module, port 23) or a serial port.

One long-lived connection. Every received line goes to the listeners (push
updates). Commands are sent one at a time with a short gap; `send` can also
collect the lines that come back, for the send_command service.
No Home Assistant imports here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .protocol import BANNER, normalize, split_lines

_LOGGER = logging.getLogger(__name__)

TRANSPORT_TCP = "tcp"
TRANSPORT_SERIAL = "serial"

# The matrix needs a moment between commands, especially at 9600 baud.
COMMAND_GAP = 0.15
# A reply is considered complete after this much silence...
REPLY_QUIET = 0.5
# ...except the full status, which pauses ~1.2 s after its header (measured on fw V1.0.1).
SLOW_REPLY_QUIET = 2.0
SLOW_COMMANDS = frozenset({"STA.", "/^Version."})
# ...or after this long in total.
REPLY_MAX = 4.0
RECONNECT_MIN = 2.0
RECONNECT_MAX = 60.0
CONNECT_TIMEOUT = 10.0

Opener = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
LineListener = Callable[[str], None]
StateListener = Callable[[bool], None]


def tcp_opener(host: str, port: int) -> Opener:
    async def _open() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=CONNECT_TIMEOUT
        )

    return _open


def serial_opener(device: str, baudrate: int) -> Opener:
    async def _open() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        # Imported here so the TCP path and the tests never need pyserial.
        import serial_asyncio_fast  # noqa: PLC0415

        return await asyncio.wait_for(
            serial_asyncio_fast.open_serial_connection(
                url=device, baudrate=baudrate, bytesize=8, parity="N", stopbits=1
            ),
            timeout=CONNECT_TIMEOUT,
        )

    return _open


class MatrixConnection:
    """Keeps a connection open, reconnects with backoff, serializes commands."""

    def __init__(self, opener: Opener, description: str) -> None:
        self._opener = opener
        self.description = description
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._stopping = False
        self._send_lock = asyncio.Lock()
        self._line_listeners: list[LineListener] = []
        self._state_listeners: list[StateListener] = []
        self._collector: list[str] | None = None
        self._last_rx = 0.0
        self._last_tx = 0.0

    # ------------------------------------------------------------ listeners

    def add_line_listener(self, listener: LineListener) -> Callable[[], None]:
        self._line_listeners.append(listener)
        return lambda: self._line_listeners.remove(listener)

    def add_state_listener(self, listener: StateListener) -> Callable[[], None]:
        self._state_listeners.append(listener)
        return lambda: self._state_listeners.remove(listener)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # ------------------------------------------------------------ lifecycle

    async def connect_once(self) -> None:
        """Open the connection or raise. Used by setup and the config flow."""
        reader, writer = await self._opener()
        self._attach(reader, writer)

    async def start(self) -> None:
        """Keep the connection up in the background."""
        self._stopping = False
        if self._run_task is None:
            self._run_task = asyncio.create_task(self._run(), name=f"gofanco {self.description}")

    async def wait_connected(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def stop(self) -> None:
        self._stopping = True
        if self._run_task:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
            self._run_task = None
        await self._close()

    async def _run(self) -> None:
        delay = RECONNECT_MIN
        while not self._stopping:
            if not self.connected:
                try:
                    await self.connect_once()
                    delay = RECONNECT_MIN
                    _LOGGER.debug("Connected to %s", self.description)
                except (OSError, TimeoutError, asyncio.TimeoutError) as err:
                    _LOGGER.debug("Connect to %s failed: %s", self.description, err)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, RECONNECT_MAX)
                    continue
            assert self._read_task is not None
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            await self._close()

    def _attach(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader, self._writer = reader, writer
        self._read_task = asyncio.create_task(self._read_loop(reader), name="gofanco reader")
        self._connected.set()
        for listener in list(self._state_listeners):
            listener(True)

    async def _close(self) -> None:
        was_connected = self.connected
        self._connected.clear()
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._read_task
        self._read_task = None
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._reader = self._writer = None
        if was_connected:
            for listener in list(self._state_listeners):
                listener(False)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        buffer = ""
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    _LOGGER.debug("%s closed the connection", self.description)
                    return
                self._last_rx = loop.time()
                buffer += chunk.decode("latin-1")
                lines, buffer = split_lines(buffer)
                # The network module's prompt has no line ending after it on some firmware.
                if buffer.startswith(BANNER) and buffer.rstrip().endswith(":"):
                    buffer = ""
                for line in lines:
                    self._dispatch(line)
        except (OSError, ConnectionError) as err:
            _LOGGER.debug("Read from %s failed: %s", self.description, err)

    def _dispatch(self, line: str) -> None:
        line = line.strip()
        if not line or line.startswith(BANNER):
            return
        _LOGGER.debug("%s <- %s", self.description, line)
        if self._collector is not None:
            self._collector.append(line)
        for listener in list(self._line_listeners):
            try:
                listener(line)
            except Exception:  # noqa: BLE001 - a bad listener must not kill the reader
                _LOGGER.exception("Line listener failed")

    # ------------------------------------------------------------ sending

    async def send(self, command: str, *, collect: bool = False) -> list[str]:
        """Send one command. With collect=True, return the lines that answered it."""
        command = normalize(command)
        async with self._send_lock:
            if not self.connected or self._writer is None:
                raise ConnectionError(f"Not connected to {self.description}")
            loop = asyncio.get_running_loop()
            wait = COMMAND_GAP - (loop.time() - self._last_tx)
            if wait > 0:
                await asyncio.sleep(wait)
            if collect:
                self._collector = []
            try:
                _LOGGER.debug("%s -> %s", self.description, command)
                self._writer.write(command.encode("ascii"))
                await self._writer.drain()
                self._last_tx = loop.time()
                if not collect:
                    return []
                start = loop.time()
                needed = SLOW_REPLY_QUIET if command in SLOW_COMMANDS else REPLY_QUIET
                while True:
                    await asyncio.sleep(0.05)
                    now = loop.time()
                    got_any = bool(self._collector)
                    quiet = now - max(self._last_rx, self._last_tx)
                    if got_any and quiet >= needed:
                        break
                    if now - start >= REPLY_MAX:
                        break
                return list(self._collector or [])
            except (OSError, ConnectionError) as err:
                await self._close()
                raise ConnectionError(f"Send to {self.description} failed: {err}") from err
            finally:
                self._collector = None

    async def send_many(self, commands: list[str]) -> None:
        for command in commands:
            await self.send(command)

    def diagnostics(self) -> dict[str, Any]:
        return {"description": self.description, "connected": self.connected}
