# SOMA Smart Shades 3 — Bluetooth for Home Assistant

Control SOMA Smart Shades 3 roller-shade motors directly over Bluetooth LE, with **no
vendor cloud, no bridge and no phone app** — and read roughly twenty things about the motor
that no other route exposes.

Works through **ESPHome Bluetooth proxies**, so the shade only has to be near a proxy, not
near your Home Assistant host.

> **Smart Shades 3 only.** The Smart Shades 2 speaks a different protocol on a different
> service, and one byte means opposite things on the two generations. See
> [Two generations](#two-generations-do-not-mix-them).

## Why this exists

The Smart Shades 3 has a Zigbee radio, and if all you want is open/close/position, Zigbee
works well. But Zigbee gives you three values. The motor knows about sixty.

| over Zigbee | additionally over Bluetooth |
| --- | --- |
| position, battery, link quality | **calibration state and travel limits**, motor speed, touch control, charger status and faults, input voltage, driver temperature, light level, per-move telemetry (duration, peak RPM, peak PWM, stall and under-voltage counts), move and boot counters, identify/beep, firmware and board revision, the Zigbee radio switch itself |

One of those matters more than the rest.

### The failure this integration was written to make visible

**A Smart Shades 3 whose travel limits have never been set refuses every move command —
and over Zigbee that is invisible.** The command is accepted. No error is logged. The link
is healthy. The motor simply reports itself fully open, forever, so a commanded position
appears to "snap back" a second later, over and over.

Nothing on the Zigbee side reveals the cause. The ZCL `configStatus` attribute reads
*operational, online, closed-loop*; `windowCoveringMode` decodes to `calibration: false`.
Both are the ZCL cluster's notions of those words and neither has anything to say about
SOMA's own limits.

Over Bluetooth it is one read. This integration surfaces it as a **Needs calibration**
problem sensor, and a move command on an uncalibrated shade fails with an error telling you
to calibrate it — rather than silently accepting a command the motor will ignore.

## Install

### HACS

1. HACS → three-dot menu → **Custom repositories**
2. Add this repository, category **Integration**
3. Install **SOMA Smart Shades 3 (Bluetooth)**, then restart Home Assistant

### Manual

Copy `custom_components/soma_ble` into your `config/custom_components/` directory and
restart Home Assistant.

## Setup

Motors are **discovered automatically** — you should get a notification once one is in
range of any Bluetooth adapter or proxy.

If you add one by hand (**Settings → Devices & services → Add integration → SOMA**) and the
list is empty, wake the motor first: there is a pinhole button on the underside, and the
front LED blinks when it is awake.

> Smart Shades 3 motors **advertise no name at all**, so they are listed by Bluetooth
> address. If you have more than one, add them all and then use the **Identify** button —
> the motor makes a noise, which is the only practical way to tell two apart.

## What you get

**Cover** — open, close, stop, set position.

**Controls**

| Entity | |
| --- | --- |
| Motor speed | 1–100 |
| Touch control | the swipe-the-motor gesture, on or off |
| Zigbee radio | on or off — see [Enabling Zigbee](#enabling-zigbee-without-the-app) |
| Identify | makes the motor beep |
| Restart motor | |

**Diagnostics** — battery percent and voltage, input voltage, external power, driver
temperature, light level, move count, boot count, firmware, charger status and fault, and
per-move telemetry: duration, peak RPM, peak PWM, stall events, under-voltage events.

The per-move telemetry is genuinely useful: a shade that is binding, over-tensioned or
fouled shows up as rising **stall events** before it fails outright.

## Calibrating without the app

A motor with no travel limits refuses to move. Setting them is normally an app job; here it
is four buttons and a service.

The raw jog only works while the shade is **uncalibrated** — that is the state calibration
happens in — so if the shade is already calibrated, press **Clear travel limits** first.

1. Get the shade to its true **top**. Either move it by hand, or use the `soma_ble.jog`
   service with `direction: open` and a small `seconds`.
2. Press **Set open limit here**.
3. Get it to its true **bottom** the same way (`direction: close`).
4. Press **Set closed limit here**.
5. Press **Save travel limits**. **Needs calibration** should clear.

⚠️ **Keep `seconds` small.** An uncalibrated motor has no end stops, so that duration is
the only thing limiting travel. The service caps it at 15 s.

⛔ **The limits latch when saved.** Once saved, the motor acknowledges further limit
commands and silently ignores them, and stops responding to jog entirely. **Clear travel
limits** is the only way back. Despite the underlying opcode being named
`CMD_RESET_SETTINGS`, it clears only the limits, the configured flag and the encoder
position — the Zigbee pairing, radio settings, speed, name and counters all survive. It is
not a factory reset.

If open and closed come out backwards, that is a motor setting (the vendor's
`CMD_SWITCH_DIRECTIONS`, `Cmd.SWITCH_DIRECTIONS` in the code), not something to fix by
re-hanging the shade.

## Enabling Zigbee without the app

The Zigbee radio is **off from the factory**, and the documented way to turn it on is the
vendor app. The **Zigbee radio** switch does it over Bluetooth instead.

⛔ The Zigbee stack only starts at boot, so after enabling it press **Restart motor**.
Skipping that looks exactly like the switch silently failing.

## Two generations, do not mix them

Most SOMA material online is for the Smart Shades **2**. Applying it to a 3 is at best
useless:

| | Smart Shades 2 | Smart Shades 3 |
| --- | --- | --- |
| Advertised name | `S`, or `RISE` pre-2018 | **none** |
| Service | `00001890-…` | `8998A466-…` |
| Meaning of `0x51` | **factory reset** | read Zigbee-enabled |

On a Smart Shades 2 a bare `0x51` wipes the motor and the documented recovery is the phone
app. This integration only ever talks to the Smart Shades 3 service, so it cannot make that
mistake — but be careful with any other tool.

## How it works

Two update paths, because the device has two very different kinds of data:

- **Passive.** Every advertisement carries position and battery, so those are live within
  seconds without ever waking the motor.
- **Active.** Everything else needs a connection, so it runs on a long interval (30 min)
  and after each command.

That split is deliberate. This is a battery device; polling it for a position it is already
broadcasting would flatten the cells for nothing.

Every Bluetooth operation goes through Home Assistant's own `bluetooth` component rather
than talking to an adapter directly, which is what makes proxies work — Home Assistant
picks whichever adapter or proxy currently hears the shade best.

## Protocol notes

`custom_components/soma_ble/protocol.py` is a standalone, dependency-free description of the
Smart Shades 3 BLE protocol — framing, the full opcode list, and the behaviours that are not
in any datasheet. It is useful on its own if you are writing something else against these
motors.

Opcode names come from the community reference
[`rzuppur/smart-shades-documentation`](https://github.com/rzuppur/smart-shades-documentation).
That reference documents names; the behaviour — the calibration latch, what
`CMD_RESET_SETTINGS` actually clears, the advertisement layout — is documented here,
because a name tells you none of it.

## Status

Early. The protocol layer is covered by tests against real device frames, and the
integration runs in a live Home Assistant instance — discovery, setup, diagnostics and
motor commands all work.

It has been tested against exactly one motor, one adapter and one proxy setup, so bug
reports are very welcome — especially from anyone running several shades, or a different
Bluetooth proxy arrangement.

Not affiliated with SOMA Smart Home.

## Licence

MIT.
