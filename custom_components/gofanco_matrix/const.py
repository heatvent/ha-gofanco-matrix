"""Constants for the gofanco Matrix44-HDBT integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "gofanco_matrix"
MANUFACTURER = "gofanco"
DEFAULT_NAME = "gofanco Matrix"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_TRANSPORT = "transport"
CONF_SERIAL_PORT = "serial_port"
CONF_BAUDRATE = "baudrate"
CONF_INPUT_NAMES = "input_names"
CONF_OUTPUT_NAMES = "output_names"
CONF_POLL_INTERVAL = "poll_interval"
CONF_AUTO_POWER_ON = "auto_power_on"

DEFAULT_TCP_PORT = 23
DEFAULT_BAUDRATE = 9600
DEFAULT_POLL_INTERVAL = 60  # seconds; the matrix also pushes changes as they happen
MIN_POLL_INTERVAL = 10
MAX_POLL_INTERVAL = 3600
DEFAULT_AUTO_POWER_ON = True

# Seconds to wait after PowerON. before the matrix accepts routing.
POWER_ON_SETTLE = 2.0

OUTPUT_LABELS = {
    1: "Output 1 (HDBaseT)",
    2: "Output 2 (HDBaseT)",
    3: "Output 3 (HDBaseT)",
    4: "Output 4 (HDMI)",
    5: "Output 5 (HDMI loop-out of 3)",
}
