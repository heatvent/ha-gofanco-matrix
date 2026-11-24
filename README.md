# gofanco Matrix44-HDBT

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/heatvent/ha-gofanco-matrix)
[![GitHub release](https://img.shields.io/github/v/release/heatvent/ha-gofanco-matrix)](https://github.com/heatvent/ha-gofanco-matrix/releases)
[![HA](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue.svg)](https://www.home-assistant.io/)

**GitHub:** https://github.com/heatvent/ha-gofanco-matrix

Custom HACS integration for the **gofanco Matrix44-HDBT** (G4-0064B) 4×4 HDMI 2.0 HDBaseT matrix (OEM model NPG-MX44E-H2). It controls the matrix over **TCP** or a **serial port**, routes it like a matrix, and exposes every command in the RS-232 guide.

Written by Heatvent (with Claude).

---

## How it works

The matrix speaks one ASCII protocol everywhere: commands end in `.` (no line ending), replies are text lines ending in `!`.

- **Network:** the matrix's built-in network module listens on **TCP port 23** and passes commands straight to the matrix. The same port works with any serial-to-TCP adapter (USR-TCP232, ESPHome stream server…) wired to the RS-232 port.
- **Serial:** the matrix's RS-232 port (3-pin Phoenix, DB9 cable in the box) on a USB-serial adapter plugged into the Home Assistant host. Default 9600 baud, 8N1.

You can switch between the two later with **Settings → Devices & services → gofanco Matrix44-HDBT → ⋮ → Reconfigure**. Entities, names and history are kept.

The matrix **pushes** a line for every change, including changes from the front panel, IR remote, web page or another controller (Control4, for example), so Home Assistant updates immediately. A full status poll (`STA.`, default every 60 s) catches anything missed.

### Standby

After `PowerOFF.` the matrix ignores every command except `PowerON.`, and its status queries return no power or routing lines. The integration detects that and shows **Power** off. With **Turn the matrix on automatically when routing** enabled (the default), picking a source while it's in standby powers it on first.

### Sharing the matrix with another controller

Several controllers can talk to the matrix at once (for example Control4 on RS-232 and Home Assistant on TCP). Each one sees the others' changes through the pushed status lines.

---

## Setup

1. Install with HACS (custom repository `https://github.com/heatvent/ha-gofanco-matrix`, category Integration), or copy `custom_components/gofanco_matrix` into your config folder.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → gofanco Matrix44-HDBT**, then choose **Network** or **Serial port**.
4. Open **Configure** to name the inputs and outputs (for example *Fire TV*, *Blu-ray*, *Bar TV*, *Theater*). The names are used in entity names and source lists.

For the network option, give the matrix a DHCP reservation in your router so its address doesn't change. The web page (`http://<matrix-ip>/`) can switch it between DHCP and a static address.

---

## Entities

| Entity | What it does | Command |
|---|---|---|
| `select.<output> source` (×4) | **Routing**: the input shown on each output | `OUTxx:yy.` |
| `switch.power` | Power / standby | `PowerON.` / `PowerOFF.` |
| `button.recall_preset_N` | Recall preset 1-9 (7-9 disabled by default) | `PresetRecallxx.` |
| `switch.front_panel_lock` | Lock the front-panel buttons | `Lock.` / `Unlock.` |
| `switch.ir_follows_video` | Receiver IR follows the video routing | `IRFVON.` / `IRFVOFF.` |
| `switch.<output> receiver power (PoC)` (×3) | Power over the HDBaseT cable | `PCATxx:ON/OFF.` |
| `switch.<output> receiver IR controls matrix` (×3, disabled) | Whether a receiver's IR eye can control the matrix | `IRRCMxxON/OFF.` |
| `switch.<output> HDMI 5V` (outputs 4, 5, disabled) | HDMI +5V | `@OUTxx.` / `$OUTxx.` |
| `select.audio_out_follows` | De-embedded audio follows a video output | `AUDIO00:yy.` |
| `select.<output> HDCP` (×5, disabled) | HDCP on / off / match display / bypass | `HDCPxxON/OFF/MAT/BYP.` |
| `select.receiver_N_ir_to` (×3, disabled) | IR routing when IR follows video is off | `IRxx:yy.` |
| `sensor.board_temperature`, `sensor.firmware` | Diagnostics | `STA.` |
| `sensor.<input> EDID`, baud rate, stored IP (disabled) | Diagnostics | `STA.` |
| `binary_sensor.<input> connected / signal`, `<output> connected` | HDMI link and TMDS per port | `STA.` |
| `button.refresh_status` | Poll now | `STA.` |

Output 5 is the HDMI loop-out of output 3, so it has no routing select of its own.

## Services

All services take an optional `config_entry_id`, which is only needed with more than one matrix.

| Service | Fields | Command |
|---|---|---|
| `gofanco_matrix.send_command` | `command` (any RS-232 command) | sent as-is (a missing `.` is added). **Returns the reply lines**, so use it with *response variable* in scripts. |
| `gofanco_matrix.set_route` | `output` (0 = all), `input` | `OUTxx:yy.` |
| `gofanco_matrix.recall_preset` / `save_preset` | `preset` 1-9 | `PresetRecallxx.` / `PresetSavexx.` |
| `gofanco_matrix.set_hdcp` | `output` (0 = all), `mode` | `HDCPxx….` |
| `gofanco_matrix.set_edid` | `input` (0 = all), `edid` 1-9 | `EDID/xx/yy.` |
| `gofanco_matrix.copy_edid` | `output` (display), `input` (0 = all) | `EDIDMxxByy.` |
| `gofanco_matrix.restore_default_edid` | | `EDIDMInit.` |
| `gofanco_matrix.set_poc` | `receiver` (0 = all), `on` | `PCATxx:ON/OFF.` |
| `gofanco_matrix.set_hdmi_5v` | `output` 4, 5 or 0, `on` | `@OUTxx.` / `$OUTxx.` |
| `gofanco_matrix.cec_source` | `input` (0 = all), `key`, `device_type` (default `04`) | `CECI…` |
| `gofanco_matrix.cec_display` | `output` 4, 5 or 0, `key`, `device_type` (default `40`) | `CECO…` |
| `gofanco_matrix.factory_reset` | `confirm: true` | `RST.`. Wipes routing, presets, EDID and HDCP settings. |

Anything else in the guide (for example `PresetSta01.`, `EDIDGOUT04.`, `STA_IN.`, `Baudrate9600.`) works through `send_command`.

### Examples

```yaml
# Show the Fire TV (input 1) on the bar TV (output 1) and the theater (output 3)
- action: gofanco_matrix.set_route
  data: { output: 1, input: 1 }
- action: gofanco_matrix.set_route
  data: { output: 3, input: 1 }

# Read a display's EDID and log it
- action: gofanco_matrix.send_command
  data: { command: "EDIDGOUT04." }
  response_variable: edid
- action: system_log.write
  data: { message: "{{ edid.reply | join(' | ') }}" }
```

---

## Notes and limits

- If the network port gets a link but never answers, the network module's settings storage may have been wiped. It's a Hi-Link HLK-RM04-type module, which can be recovered by rewriting its flash chip. RS-232 keeps working either way, so switch the integration to serial with **Reconfigure** in the meantime.
- The matrix's `GetGuiIP.` / `SetGuiIP:` value is stored in the matrix and isn't always the module's live address when the module is on DHCP. The integration shows it as *Matrix stored IP* (disabled by default).
- Replies are free text on firmware **V1.0.1 / CPLD V1.0.0**. Other firmware may word things differently; `send_command` and the diagnostics download show the raw lines.

## Development

```bash
pip install pytest-homeassistant-custom-component
python -m pytest -q
```

`protocol.py` (builders and parser) and `connection.py` (TCP/serial transport) have no Home Assistant imports, and the tests run them against replies captured from real hardware.

## License

MIT. See [LICENSE](LICENSE). Unofficial: gofanco did not make and does not support this integration. The gofanco name and logo are trademarks of gofanco and are used only to identify the device this integration controls.
