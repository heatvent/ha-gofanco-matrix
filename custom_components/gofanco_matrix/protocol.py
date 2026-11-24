"""gofanco Matrix44-HDBT ASCII protocol: command builders and reply parser.

No Home Assistant imports here, so it can be tested on its own.

Commands are plain ASCII ending in "." with no line ending. The matrix answers
with CR/LF-terminated lines, most ending in "!". It also pushes the same lines
unsolicited when something changes (front panel, IR remote, another controller).
In standby (after PowerOFF.) it ignores every command except PowerON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INPUTS = 4
ROUTABLE_OUTPUTS = 4  # output 5 is the HDMI loop-out of output 3
OUTPUTS = 5
RECEIVERS = 3  # HDBaseT outputs 1-3 (PoC, remote IR)
HDMI_5V_OUTPUTS = (4, 5)
CEC_DISPLAY_OUTPUTS = (4, 5)
PRESETS = 9
BUILTIN_EDIDS = 9  # 9 = user-defined

HDCP_MODES = {"on": "ON", "off": "OFF", "match": "MAT", "bypass": "BYP"}
BAUD_RATES = (2400, 4800, 9600, 19200, 38400, 57600, 115200)

CEC_SOURCE_KEYS = {
    "power_on": "6D",
    "power_off": "6C",
    "menu": "0A",
    "up": "01",
    "down": "02",
    "left": "03",
    "right": "04",
    "enter": "00",
    "back": "09",
    "exit": "0D",
}
CEC_DISPLAY_POWER = {"power_on": "04", "power_off": "36"}
CEC_DISPLAY_KEYS = {"volume_up": "41", "volume_down": "42", "mute": "43"}

BANNER = "Please Input Your Command"


class CommandError(ValueError):
    """A command argument is out of range."""


def _two(value: int) -> str:
    return f"{int(value):02d}"


def _check(value: int, low: int, high: int, what: str) -> int:
    value = int(value)
    if not low <= value <= high:
        raise CommandError(f"{what} must be {low}-{high}, got {value}")
    return value


def normalize(command: str) -> str:
    """Strip whitespace and add the trailing '.' if it is missing."""
    command = command.strip()
    if not command:
        raise CommandError("empty command")
    return command if command.endswith(".") else command + "."


# --------------------------------------------------------------- builders


def cmd_route(output: int, input_: int) -> str:
    """OUTxx:yy. — output 0 means all outputs."""
    _check(output, 0, ROUTABLE_OUTPUTS, "output")
    _check(input_, 1, INPUTS, "input")
    return f"OUT{_two(output)}:{_two(input_)}."


def cmd_power(on: bool) -> str:
    return "PowerON." if on else "PowerOFF."


def cmd_lock(locked: bool) -> str:
    return "Lock." if locked else "Unlock."


def cmd_preset_save(preset: int) -> str:
    return f"PresetSave{_two(_check(preset, 1, PRESETS, 'preset'))}."


def cmd_preset_recall(preset: int) -> str:
    return f"PresetRecall{_two(_check(preset, 1, PRESETS, 'preset'))}."


def cmd_preset_status(preset: int) -> str:
    return f"PresetSta{_two(_check(preset, 1, PRESETS, 'preset'))}."


def cmd_hdcp(output: int, mode: str) -> str:
    """HDCPxxON/OFF/MAT/BYP. — output 0 means all."""
    _check(output, 0, OUTPUTS, "output")
    if mode not in HDCP_MODES:
        raise CommandError(f"HDCP mode must be one of {', '.join(HDCP_MODES)}")
    return f"HDCP{_two(output)}{HDCP_MODES[mode]}."


def cmd_hdmi_5v(output: int, on: bool) -> str:
    """@OUTxx. (on) / $OUTxx. (off) — HDMI outputs 4, 5 or 0 for both."""
    if int(output) not in (0, *HDMI_5V_OUTPUTS):
        raise CommandError("HDMI 5V applies to output 4, 5 or 0 (all)")
    return f"{'@' if on else '$'}OUT{_two(output)}."


def cmd_poc(receiver: int, on: bool) -> str:
    """PCATxx:ON./OFF. — power over cable to HDBaseT receiver 1-3 (0 = all)."""
    _check(receiver, 0, RECEIVERS, "receiver")
    return f"PCAT{_two(receiver)}:{'ON' if on else 'OFF'}."


def cmd_ir_follow_video(on: bool) -> str:
    return "IRFVON." if on else "IRFVOFF."


def cmd_ir_route(local_out: int, receiver: int) -> str:
    """IRxx:yy. — send remote receiver yy's IR to local IR out xx."""
    _check(local_out, 1, ROUTABLE_OUTPUTS, "local IR out")
    _check(receiver, 0, RECEIVERS, "receiver")
    return f"IR{_two(local_out)}:{_two(receiver)}."


def cmd_receiver_ir_controls_matrix(receiver: int, on: bool) -> str:
    """IRRCMxxON./OFF. — whether a receiver's IR eye can control the matrix."""
    _check(receiver, 0, RECEIVERS, "receiver")
    return f"IRRCM{_two(receiver)}{'ON' if on else 'OFF'}."


def cmd_audio_source(output: int) -> str:
    """AUDIO00:yy. — de-embedded audio follows video output yy."""
    return f"AUDIO00:{_two(_check(output, 1, ROUTABLE_OUTPUTS, 'output'))}."


def cmd_edid_builtin(input_: int, edid: int) -> str:
    """EDID/xx/yy. — input 0 means all inputs; edid 9 is the user-defined one."""
    _check(input_, 0, INPUTS, "input")
    return f"EDID/{_two(input_)}/{_two(_check(edid, 1, BUILTIN_EDIDS, 'EDID'))}."


def cmd_edid_copy(output: int, input_: int) -> str:
    """EDIDMxxByy. — copy output xx's display EDID to input yy (0 = all)."""
    _check(output, 1, OUTPUTS, "output")
    _check(input_, 0, INPUTS, "input")
    return f"EDIDM{_two(output)}B{_two(input_)}."


def cmd_edid_read(output: int) -> str:
    return f"EDIDGOUT{_two(_check(output, 1, OUTPUTS, 'output'))}."


def cmd_edid_default() -> str:
    return "EDIDMInit."


def cmd_edid_status(input_: int) -> str:
    return f"EDIDSTA{_two(_check(input_, 0, INPUTS, 'input'))}."


def cmd_cec_source(input_: int, key: str, device_type: str = "04") -> str:
    """CECI[AA][BB]44[DD]. — AA input (FF = all), BB CEC device type."""
    _check(input_, 0, INPUTS, "input")
    if key not in CEC_SOURCE_KEYS:
        raise CommandError(f"CEC source key must be one of {', '.join(CEC_SOURCE_KEYS)}")
    aa = "FF" if int(input_) == 0 else _two(input_)
    return f"CECI{aa}{device_type}44{CEC_SOURCE_KEYS[key]}."


def cmd_cec_display(output: int, key: str, device_type: str = "40") -> str:
    """CECO[AA][BB][..]. — HDMI outputs 4, 5 (0 = all)."""
    if int(output) not in (0, *CEC_DISPLAY_OUTPUTS):
        raise CommandError("CEC display control applies to output 4, 5 or 0 (all)")
    aa = "FF" if int(output) == 0 else _two(output)
    if key in CEC_DISPLAY_POWER:
        return f"CECO{aa}{device_type}{CEC_DISPLAY_POWER[key]}."
    if key in CEC_DISPLAY_KEYS:
        return f"CECO{aa}{device_type}44{CEC_DISPLAY_KEYS[key]}."
    raise CommandError(
        f"CEC display key must be one of {', '.join([*CEC_DISPLAY_POWER, *CEC_DISPLAY_KEYS])}"
    )


def cmd_set_ip(ip: str) -> str:
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip.strip()):
        raise CommandError("not an IPv4 address")
    return f"SetGuiIP:{ip.strip()}."


STATUS_ALL = "STA."
STATUS_VIDEO = "STA_VIDEO."
STATUS_INFO = ("/*Name.", "/*Type.", "/^Version.")
FACTORY_RESET = "RST."


# --------------------------------------------------------------- state


@dataclass
class MatrixState:
    """Everything the matrix reports. None = not reported yet."""

    power: bool | None = None
    routes: dict[int, int] = field(default_factory=dict)  # output -> input
    front_panel_locked: bool | None = None
    ir_follow_video: bool | None = None
    temperature: int | None = None
    baud_rate: int | None = None
    gui_ip: str | None = None
    firmware: str | None = None
    cpld: str | None = None
    model_name: str | None = None
    model_type: str | None = None
    poc: dict[int, bool] = field(default_factory=dict)  # receiver -> on
    hdmi_5v: dict[int, bool] = field(default_factory=dict)  # output -> on
    receiver_ir_controls_matrix: dict[int, bool] = field(default_factory=dict)
    ir_routes: dict[int, int] = field(default_factory=dict)  # receiver -> local IR out
    audio_source: int | None = None  # video output the audio out follows
    hdcp: dict[int, str] = field(default_factory=dict)  # output -> on/off/match/bypass
    edid: dict[int, str] = field(default_factory=dict)  # input -> description
    input_link: dict[int, bool] = field(default_factory=dict)
    input_tmds: dict[int, bool] = field(default_factory=dict)
    output_link: dict[int, bool] = field(default_factory=dict)


_RE_ROUTE = re.compile(r"Output\s*(\d+)\s*Switch\s*To\s*In\s*(\d+)", re.I)
_RE_POWER = re.compile(r"^Power\s*(ON|OFF)!?$", re.I)
_RE_POC = re.compile(r"^CAT\s*(\d+)\s*Power\s*(ON|OFF)", re.I)
_RE_TEMP = re.compile(r"Temperature\s*is\s*(-?\d+)", re.I)
_RE_BAUD = re.compile(r"Baudrate\s*Is\s*(\d+)", re.I)
_RE_IP = re.compile(r"(?:GUI_IP|SetGuiIP)\s*:\s*(\d+\.\d+\.\d+\.\d+)", re.I)
_RE_5V = re.compile(r"^Turn\s*(ON|OFF)\s*Output\s*(\d+)", re.I)
_RE_IRRCM = re.compile(r"IR\s*Remote\s*(\d+)\s*Control\s*MCU\s*(ON|OFF)", re.I)
_RE_AUDIO = re.compile(r"Audio\s*Out\s*\d+\s*Switch\s*To\s*Video\s*Out\s*(\d+)", re.I)
_RE_IRFV = re.compile(r"IR\s*Follow\s*Video\s*(ON|OFF)", re.I)
_RE_IRROUTE = re.compile(r"Local\s*(\d+)\s*IR\s*Out\s*Switch\s*To\s*Remote\s*(\d+)\s*IR\s*IN", re.I)
_RE_EDID = re.compile(r"^Input\s*(\d+)\s*EDID\s*From\s*(.+?)!?$", re.I)
_RE_HDCP = re.compile(r"^OUT\s*(\d+)\s*HDCP\s*(.+?)!?$", re.I)
_RE_VERSION = re.compile(r"^V\d+(\.\d+)+$")
_RE_CPLD = re.compile(r"^CPLD\s*:\s*(V[\d.]+)", re.I)
_RE_TABLE_HEAD = re.compile(r"^(IN|OUT)((?:\s+\d+)+)\s*$")
_RE_TABLE_ROW = re.compile(r"^(LINK|TMDS)((?:\s+[YN])+)\s*$", re.I)


def _hdcp_mode(text: str) -> str:
    text = text.strip().upper()
    if text.startswith("MAT"):
        return "match"
    if text.startswith("BYP"):
        return "bypass"
    if text.startswith("OFF"):
        return "off"
    if text.startswith("ON"):
        return "on"
    return text.lower()


class Parser:
    """Feeds reply lines into a MatrixState. Returns True if state changed."""

    def __init__(self, state: MatrixState | None = None) -> None:
        self.state = state or MatrixState()
        self._table: tuple[str, list[int]] | None = None

    def feed(self, line: str) -> bool:
        line = line.strip()
        if not line or line.startswith(BANNER):
            return False
        before = repr(self.state)
        self._feed(line)
        return repr(self.state) != before

    def _feed(self, line: str) -> None:
        s = self.state
        if m := _RE_TABLE_HEAD.match(line):
            self._table = (m.group(1).upper(), [int(x) for x in m.group(2).split()])
            return
        if (m := _RE_TABLE_ROW.match(line)) and self._table:
            kind, ports = self._table
            values = [v.upper() == "Y" for v in m.group(2).split()]
            row = m.group(1).upper()
            target = (
                s.output_link if kind == "OUT"
                else s.input_tmds if row == "TMDS"
                else s.input_link
            )
            for port, value in zip(ports, values):
                target[port] = value
            return
        self._table = None

        if m := _RE_ROUTE.search(line):
            s.routes[int(m.group(1))] = int(m.group(2))
            # Any routing reply means the matrix is awake.
            s.power = True
        elif m := _RE_POWER.match(line):
            s.power = m.group(1).upper() == "ON"
        elif m := _RE_POC.match(line):
            s.poc[int(m.group(1))] = m.group(2).upper() == "ON"
        elif "Front Panel Locked" in line:
            s.front_panel_locked = True
        elif re.search(r"Front\s*Panel\s*Un\s*Lock", line, re.I):
            s.front_panel_locked = False
        elif m := _RE_TEMP.search(line):
            s.temperature = int(m.group(1))
        elif m := _RE_BAUD.search(line):
            s.baud_rate = int(m.group(1))
        elif m := _RE_IP.search(line):
            s.gui_ip = m.group(1)
        elif m := _RE_5V.match(line):
            s.hdmi_5v[int(m.group(2))] = m.group(1).upper() == "ON"
        elif m := _RE_IRRCM.search(line):
            s.receiver_ir_controls_matrix[int(m.group(1))] = m.group(2).upper() == "ON"
        elif m := _RE_AUDIO.search(line):
            s.audio_source = int(m.group(1))
        elif m := _RE_IRFV.search(line):
            s.ir_follow_video = m.group(1).upper() == "ON"
        elif m := _RE_IRROUTE.search(line):
            s.ir_routes[int(m.group(2))] = int(m.group(1))
        elif m := _RE_EDID.match(line):
            s.edid[int(m.group(1))] = m.group(2).strip()
        elif m := _RE_HDCP.match(line):
            s.hdcp[int(m.group(1))] = _hdcp_mode(m.group(2))
        elif m := _RE_CPLD.match(line):
            s.cpld = m.group(1)
        elif _RE_VERSION.match(line):
            s.firmware = line
        elif "Matrix Switcher" in line:
            s.model_type = line
        elif "HDBT" in line.upper() and len(line) < 40:
            s.model_name = line


def reply_shows_awake(lines: list[str]) -> bool:
    """True if a status reply came from a powered-on matrix (it has power/routing lines)."""
    return any(_RE_POWER.match(line.strip()) or _RE_ROUTE.search(line) for line in lines)


def split_lines(buffer: str) -> tuple[list[str], str]:
    """Split complete CR/LF lines off a receive buffer; return (lines, rest)."""
    parts = re.split(r"\r\n|\r|\n", buffer)
    return [p for p in parts[:-1]], parts[-1]
