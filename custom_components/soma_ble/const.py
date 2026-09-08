"""Constants for the SOMA Smart Shades 3 (BLE) integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "soma_ble"

CONF_ADDRESS = "address"

#: How often to connect for the full diagnostic read. Position and battery do NOT wait for
#: this -- they arrive passively in every advertisement, so this interval only governs the
#: expensive data (charger, temperatures, motor telemetry). Kept long on purpose: this is a
#: battery device and a connection is the costly thing it does.
SCAN_INTERVAL = timedelta(minutes=30)

#: A connection attempt is given this long before it is treated as unreachable.
CONNECT_TIMEOUT = 30.0

#: The device has no notify on its response characteristic, so every command is
#: write-then-read. Rather than sleep for the worst case on every one of ~27 getters --
#: which cost ~19 s of connected time per refresh on a battery device -- the reply is
#: polled for, and recognised by its opcode.
REPLY_POLL = 0.08
REPLY_TIMEOUT = 1.5

#: An SS3 is a sleepy device that wakes on connection. Retry rather than fail on the first
#: miss -- a single failed connect is normal, not a fault.
CONNECT_RETRIES = 3

MANUFACTURER = "SOMA Smart Home"
MODEL = "Smart Shades 3"
