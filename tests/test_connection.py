"""Connection: line dispatch, reply collection, command gap — over an in-memory fake device."""

import asyncio

from .conftest import load

connection = load("connection")


class FakeWriter:
    def __init__(self, device: "FakeMatrix") -> None:
        self.device = device
        self.closed = False

    def write(self, data: bytes) -> None:
        self.device.received(data.decode())

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True
        self.device.reader.feed_eof()

    async def wait_closed(self) -> None:
        return None


class FakeMatrix:
    """Answers like the real matrix: replies only while powered on (except PowerON.)."""

    def __init__(self, powered: bool = True) -> None:
        self.powered = powered
        self.commands: list[str] = []
        self.reader = asyncio.StreamReader()
        self.writer = FakeWriter(self)

    async def open(self):
        self.reader.feed_data(b"Please Input Your Command :\r\n")
        return self.reader, self.writer

    def received(self, command: str) -> None:
        self.commands.append(command)
        if command == "PowerON.":
            self.powered = True
            self._reply("Power ON!", "Output 01 Switch To In 01!")
        elif not self.powered:
            return
        elif command == "STA_VIDEO.":
            self._reply(*(f"Output 0{o} Switch To In 01!" for o in range(1, 5)))
        elif command.startswith("OUT"):
            out, inp = command[3:5], command[6:8]
            self._reply(f"Output {out} Switch To In {inp}!")
        elif command == "STA.":
            # The real matrix pauses ~1.2 s after the header.
            loop = asyncio.get_running_loop()
            loop.call_later(0.02, self.reader.feed_data, b"GUI Or RS232 Query Status:\r\n")
            loop.call_later(1.2, self.reader.feed_data, b"V1.0.1\r\nPower ON!\r\n")
        elif command == "PowerOFF.":
            self._reply("Power OFF!")
            self.powered = False

    def _reply(self, *lines: str) -> None:
        loop = asyncio.get_running_loop()
        data = "".join(f"{line}\r\n" for line in lines).encode()
        loop.call_later(0.02, self.reader.feed_data, data)


def run(coro):
    return asyncio.run(coro)


def test_collects_reply_and_dispatches_lines():
    async def main():
        device = FakeMatrix()
        conn = connection.MatrixConnection(device.open, "fake")
        seen: list[str] = []
        conn.add_line_listener(seen.append)
        await conn.connect_once()
        reply = await conn.send("STA_VIDEO", collect=True)
        await conn.stop()
        return device, reply, seen

    device, reply, seen = run(main())
    assert device.commands == ["STA_VIDEO."]
    assert reply == [f"Output 0{o} Switch To In 01!" for o in range(1, 5)]
    assert seen == reply  # the banner is filtered out


def test_standby_is_silent_until_power_on():
    async def main():
        device = FakeMatrix(powered=False)
        conn = connection.MatrixConnection(device.open, "fake")
        await conn.connect_once()
        silent = await conn.send("STA_VIDEO.", collect=True)
        woke = await conn.send("PowerON.", collect=True)
        await conn.stop()
        return silent, woke

    silent, woke = run(main())
    assert silent == []
    assert woke[0] == "Power ON!"


def test_commands_are_serialized_with_gap():
    async def main():
        device = FakeMatrix()
        conn = connection.MatrixConnection(device.open, "fake")
        await conn.connect_once()
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.gather(conn.send("OUT01:02."), conn.send("OUT02:03."), conn.send("OUT03:04."))
        elapsed = loop.time() - start
        await conn.stop()
        return device, elapsed

    device, elapsed = run(main())
    assert device.commands == ["OUT01:02.", "OUT02:03.", "OUT03:04."]
    assert elapsed >= 2 * connection.COMMAND_GAP * 0.9


def test_full_status_waits_through_the_pause():
    async def main():
        device = FakeMatrix()
        conn = connection.MatrixConnection(device.open, "fake")
        await conn.connect_once()
        reply = await conn.send("STA.", collect=True)
        await conn.stop()
        return reply

    assert run(main()) == ["GUI Or RS232 Query Status:", "V1.0.1", "Power ON!"]


def test_send_when_disconnected_raises():
    async def main():
        conn = connection.MatrixConnection(FakeMatrix().open, "fake")
        try:
            await conn.send("STA.")
        except ConnectionError:
            return True
        return False

    assert run(main()) is True
