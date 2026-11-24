"""Builders and parser, using replies captured from a real Matrix44-HDBT (fw V1.0.1)."""

import pytest

from .conftest import load

protocol = load("protocol")

STA_REPLY = """
GUI Or RS232 Query Status:
HDMI 2.0 4x4 Matrix Switcher
Matrix44-HDBT TX
V1.0.1
Power ON!
CAT 01 Power ON!
CAT 02 Power OFF!
CAT 03 Power OFF!
Front Panel UnLock!
The Board Temperature is 21 Dgrees Celcius!
Local RS232 Baudrate Is 9600!
GUI_IP:192.168.68.150!
Output 01 Switch To In 01!
Output 02 Switch To In 03!
Output 03 Switch To In 01!
Output 04 Switch To In 03!
Turn ON Output 04!
Turn ON Output 05!
IR Remote 01 Control MCU ON!
IR Remote 02 Control MCU ON!
IR Remote 03 Control MCU ON!
Audio Out 01 Switch To Video Out 01!
IR Follow Video ON!
Local 01 IR Out Switch To Remote 01 IR IN!
Local 03 IR Out Switch To Remote 02 IR IN!
Local 01 IR Out Switch To Remote 03 IR IN!
IN    1  2  3  4
LINK  N  Y  N  N
TMDS  N  Y  N  N
OUT   1  2  3  4  5
LINK  Y  N  N  N  N
Input 01 EDID From User Define EDID!
Input 02 EDID From User Define EDID!
Input 03 EDID From User Define EDID!
Input 04 EDID From User Define EDID!
OUT 01 HDCP MAT DISPLAY!
OUT 02 HDCP MAT DISPLAY!
OUT 03 HDCP BYPASS!
OUT 04 HDCP MAT DISPLAY!
OUT 05 HDCP MAT DISPLAY!
"""


def parse(text: str):
    parser = protocol.Parser()
    for line in text.splitlines():
        parser.feed(line)
    return parser.state


def test_full_status():
    s = parse(STA_REPLY)
    assert s.power is True
    assert s.routes == {1: 1, 2: 3, 3: 1, 4: 3}
    assert s.poc == {1: True, 2: False, 3: False}
    assert s.front_panel_locked is False
    assert s.temperature == 21
    assert s.baud_rate == 9600
    assert s.gui_ip == "192.168.68.150"
    assert s.hdmi_5v == {4: True, 5: True}
    assert s.receiver_ir_controls_matrix == {1: True, 2: True, 3: True}
    assert s.audio_source == 1
    assert s.ir_follow_video is True
    assert s.ir_routes == {1: 1, 2: 3, 3: 1}
    assert s.input_link == {1: False, 2: True, 3: False, 4: False}
    assert s.input_tmds == {1: False, 2: True, 3: False, 4: False}
    assert s.output_link == {1: True, 2: False, 3: False, 4: False, 5: False}
    assert s.edid[1] == "User Define EDID"
    assert s.hdcp == {1: "match", 2: "match", 3: "bypass", 4: "match", 5: "match"}
    assert s.firmware == "V1.0.1"
    assert s.model_name == "Matrix44-HDBT TX"
    assert s.model_type == "HDMI 2.0 4x4 Matrix Switcher"


def test_version_and_cpld():
    s = parse("V1.0.1\r\nCPLD:V1.0.0\r\n")
    assert s.firmware == "V1.0.1"
    assert s.cpld == "V1.0.0"


def test_push_updates_and_change_flag():
    parser = protocol.Parser()
    assert parser.feed("Output 03 Switch To In 02!") is True
    assert parser.feed("Output 03 Switch To In 02!") is False
    assert parser.feed("Power OFF!") is True
    assert parser.state.power is False
    assert parser.feed("Front Panel Locked!") is True
    assert parser.state.front_panel_locked is True
    assert parser.feed("IR Follow Video OFF!") is True
    assert parser.feed("Turn OFF Output 05!") is True
    assert parser.state.hdmi_5v[5] is False


def test_preset_and_banner_lines_do_not_touch_routes():
    s = parse("Please Input Your Command :\nPreset 01 Sta:\nOut 01 In 02!\nOut 02 In 02!\n")
    assert s.routes == {}
    assert s.power is None


def test_audio_line_is_not_a_route():
    s = parse("Audio Out 01 Switch To Video Out 03!")
    assert s.routes == {}
    assert s.audio_source == 3


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        (protocol.cmd_route(1, 2), "OUT01:02."),
        (protocol.cmd_route(0, 4), "OUT00:04."),
        (protocol.cmd_power(True), "PowerON."),
        (protocol.cmd_power(False), "PowerOFF."),
        (protocol.cmd_lock(True), "Lock."),
        (protocol.cmd_lock(False), "Unlock."),
        (protocol.cmd_preset_save(3), "PresetSave03."),
        (protocol.cmd_preset_recall(9), "PresetRecall09."),
        (protocol.cmd_preset_status(1), "PresetSta01."),
        (protocol.cmd_hdcp(0, "match"), "HDCP00MAT."),
        (protocol.cmd_hdcp(5, "bypass"), "HDCP05BYP."),
        (protocol.cmd_hdmi_5v(4, True), "@OUT04."),
        (protocol.cmd_hdmi_5v(0, False), "$OUT00."),
        (protocol.cmd_poc(2, True), "PCAT02:ON."),
        (protocol.cmd_ir_follow_video(False), "IRFVOFF."),
        (protocol.cmd_ir_route(3, 1), "IR03:01."),
        (protocol.cmd_receiver_ir_controls_matrix(1, False), "IRRCM01OFF."),
        (protocol.cmd_audio_source(2), "AUDIO00:02."),
        (protocol.cmd_edid_builtin(0, 9), "EDID/00/09."),
        (protocol.cmd_edid_copy(4, 1), "EDIDM04B01."),
        (protocol.cmd_edid_read(4), "EDIDGOUT04."),
        (protocol.cmd_edid_default(), "EDIDMInit."),
        (protocol.cmd_edid_status(0), "EDIDSTA00."),
        (protocol.cmd_cec_source(0, "power_on"), "CECIFF04446D."),
        (protocol.cmd_cec_source(2, "menu", "04"), "CECI0204440A."),
        (protocol.cmd_cec_display(4, "power_off"), "CECO044036."),
        (protocol.cmd_cec_display(0, "volume_up"), "CECOFF404441."),
        (protocol.cmd_set_ip("192.168.68.150"), "SetGuiIP:192.168.68.150."),
    ],
)
def test_builders(built, expected):
    assert built == expected


@pytest.mark.parametrize(
    "call",
    [
        lambda: protocol.cmd_route(5, 1),
        lambda: protocol.cmd_route(1, 0),
        lambda: protocol.cmd_preset_recall(10),
        lambda: protocol.cmd_hdcp(1, "maybe"),
        lambda: protocol.cmd_hdmi_5v(1, True),
        lambda: protocol.cmd_poc(4, True),
        lambda: protocol.cmd_cec_display(1, "power_on"),
        lambda: protocol.cmd_set_ip("not-an-ip"),
        lambda: protocol.normalize("   "),
    ],
)
def test_builders_reject_bad_args(call):
    with pytest.raises(protocol.CommandError):
        call()


def test_standby_detection():
    # Seen on real hardware: in standby STA. returns nothing, or only header/model/version.
    assert protocol.reply_shows_awake([]) is False
    assert protocol.reply_shows_awake(
        ["GUI Or RS232 Query Status:", "HDMI 2.0 4x4 Matrix Switcher", "Matrix44-HDBT TX", "V1.0.1"]
    ) is False
    assert protocol.reply_shows_awake(STA_REPLY.splitlines()) is True
    assert protocol.reply_shows_awake(["Output 01 Switch To In 02!"]) is True


def test_normalize_and_split():
    assert protocol.normalize(" STA ") == "STA."
    assert protocol.normalize("STA_VIDEO.") == "STA_VIDEO."
    lines, rest = protocol.split_lines("Power ON!\r\nOutput 01 Swi")
    assert lines == ["Power ON!"]
    assert rest == "Output 01 Swi"
