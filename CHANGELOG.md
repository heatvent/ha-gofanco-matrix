# Changelog

## 1.0.1 — 2026-11-23
- Integration icon and logo now use the gofanco logo, with a light-lettered logo for dark themes.
- Power-on reads full status straight away, and the device keeps its firmware version when Home Assistant starts while the matrix is in standby.

## 1.0.0 — 2026-11-23

- First release.
- Connects over TCP (the matrix's built-in network module on port 23, or any serial-to-TCP adapter) or a local serial port; switch between them later with **Reconfigure** without losing entities.
- Live updates: the matrix pushes every change (front panel, IR remote, Control4, web page) and the integration applies it at once; a full `STA.` poll (default 60 s) is the safety net.
- Matrix routing: one source select per output, `set_route` service (output 0 = all), preset recall buttons and services.
- Power switch with standby detection (in standby the matrix ignores everything except `PowerON.`); optional automatic power-on before routing.
- Switches for front-panel lock, IR follows video, PoC per HDBaseT receiver, receiver IR control of the matrix, HDMI 5V on outputs 4/5.
- Selects for HDCP mode per output, de-embedded audio source and IR routing per receiver.
- Sensors for board temperature, firmware, EDID per input, baud rate and stored IP; connectivity sensors for each input (link + signal) and output.
- Services for every RS-232 command: `send_command` (returns the reply), presets, HDCP, EDID (built-in, copy from display, restore default), PoC, HDMI 5V, CEC to sources and displays, guarded factory reset.
- Diagnostics download.
