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
#: which would hold a battery device's link open far longer than it needs -- the reply is
#: polled for, and recognised by its opcode.
REPLY_POLL = 0.08
REPLY_TIMEOUT = 1.5

#: An SS3 is a sleepy device that wakes on connection. Retry rather than fail on the first
#: miss -- a single failed connect is normal, not a fault.
CONNECT_RETRIES = 3

MANUFACTURER = "SOMA Smart Home"
MODEL = "Smart Shades 3"

#: How long a command will wait for a CONNECTABLE advertisement before giving up.
#:
#: Home Assistant can only open a connection while a recent CONNECTABLE advertisement sits
#: in its discovered set. That record can go stale for minutes at a time, and a command
#: issued while it is stale fails immediately with "no connectable path". Waiting for the
#: next advertisement turns that from "nothing happened" into "it worked, after a moment".
#:
#: The motor's radio is not the cause. `GET_ADV_INTERVAL` reads 0xF000A0, which is the usual BLE min/max pair: 160 and 240
#: units of 0.625 ms, i.e. 100 ms and 150 ms, so the radio advertises ~10x a second. The
#: much slower rate at which Home Assistant delivers advertisement CALLBACKS is not the
#: radio's rate -- the stack collapses unchanged advertisement data. The gap is upstream of
#: the radio, in the proxy or in the host stack; this wait covers it.
ADVERTISEMENT_WAIT = 150.0

#: Breathing room between a command and the connected refresh that follows it. The motor
#: has just dropped the link and is often still moving, and an instant reconnect is often
#: refused.
POST_COMMAND_SETTLE = 3.0

#: Default duration for the jog buttons, in seconds. Small on purpose: an uncalibrated
#: motor has NO end stops, so this is the only thing bounding travel.
DEFAULT_JOG_SECONDS = 2.0

#: Pause between a move command and the read-back that follows it on the SAME link.
#: Not cosmetic. `GET_MOTOR_MOVING` asked the instant the command lands can answer
#: "false" because the motor has not started yet, and the cover then shows neither
#: `opening` nor `closing` for the whole travel -- the move looks like it was ignored,
#: which is the exact symptom this integration exists to stop misreporting.
READ_BACK_DELAY = 1.0

#: When to re-read `motor moving` after a move command, in seconds from the command.
#:
#: Without this the cover lies for half an hour. The read-back that rides on the move's
#: own connection necessarily catches the motor while it is still running, so it records
#: `moving = True` -- and nothing else ever clears it: advertisements carry position and
#: battery only, so the next connected read is `SCAN_INTERVAL` away. The cover would show
#: "Opening" long after the shade had stopped.
#:
#: Bounded on purpose. Each entry costs one short connection, and this is a battery device
#: for anyone not running it on external power -- so it gives up rather than polling, and
#: stops early the moment the motor reports itself stopped. Four short reads still cost far
#: less connected time than a single 27-getter refresh.
MOTION_FOLLOW_UP = (8.0, 16.0, 32.0, 64.0)

#: A command already waiting for an advertisement blocks for up to ADVERTISEMENT_WAIT,
#: which looks exactly like nothing happening -- so a second press is the natural response.
#: Queueing both is the hazard: on an uncalibrated motor, with no end stops, two jogs that
#: land back-to-back travel twice as far as either was meant to. Refuse instead.
COMMAND_BUSY_MESSAGE = (
    "A command is already waiting for this shade to advertise. Give it a moment rather "
    "than pressing again -- two moves that land together travel twice as far."
)
