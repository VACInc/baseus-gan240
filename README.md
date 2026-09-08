# Baseus BS-GaN240 for Home Assistant

Local Bluetooth integration for **Baseus CCGAN240CS / BS-GaN240**. Creates four
switches for USB C1, USB C2, USB C3 and USB A, plus all read-only telemetry
identified in the vendor app: total and per-output watts, internal temperature,
negotiated charging protocols, port fault bitmaps, priority output, display and
child-lock state, and Bluetooth/DC module versions. The protocol does not expose
voltage or current readings, so those are not fabricated from wattage. No cloud
account, pairing secret, DC switch, restoration or scheduled switching.

## Status

Developed against Home Assistant **2026.9.0** and Python 3.14. Unit tests use
real Home Assistant imports with synthetic Bluetooth devices. Hardware status
and control validation are separate from unit-test coverage.

## Installation requirements

- Home Assistant 2026.9.0 or later (only 2026.9.0 tested).
- The built-in Bluetooth integration, with a supported local connectable adapter
  or an already configured ESPHome Bluetooth proxy supporting **active GATT
  connections**, in range and with a free connection slot.
- Charger powered on. Close the vendor app and other BLE clients when testing;
  simultaneous external controllers are not supported.
- Dependency `bleak-retry-connector==4.7.0` matches the target HA Bluetooth
  integration. HA installs it; no separate scanner or direct proxy API is used.

## Installation

In HACS, open **Custom repositories**, add
`https://github.com/VACInc/baseus-gan240`, and select **Integration**.
Download Baseus BS-GaN240, then restart Home Assistant. This is a custom
repository, not a HACS default listing.

Use Settings > Devices & services > Add integration > Baseus BS-GaN240.
Enter the charger's Bluetooth address or confirm its Bluetooth discovery.
Setup sends only a status query. Unloading and reloading use the normal
Home Assistant config-entry lifecycle. No port state is saved or restored.

For manual installation, copy `custom_components/baseus_gan240` into the
Home Assistant configuration's `custom_components` directory and restart.

## Behavior and safety

Switch on clears its disable bit; switch off sets it. C1=0x04, C2=0x08,
C3=0x10, A=0x20. Every operation first queries actual state and modifies only
that bit, preserving all other 16-bit mask bits, including 0x01, DC=0x02 and
unknown high bits. A matching current state causes no control write.

One device lock serializes read/modify/write/verify; coordinator publication is
also serialized. Connection retries happen only before payload transmission.
There is exactly one control-write attempt. A timeout, disconnect, cancellation,
malformed status or readback mismatch fails visibly and does not retry the
control command. A subsequent request must obtain a new read before deciding
whether a write is needed. No optimistic state and no automatic restoration.
Setup and each 60-second poll are read-only. A poll reads all telemetry registers
sequentially over one owned connection and notification subscription. Poll errors
make the integration entities unavailable; successful subsequent reads recover
availability. An idle disconnect is normal because each transaction releases its
BLE connection/proxy slot.

### Exact protocol

- GATT service: `0000ae30-0000-1000-8000-00805f9b34fb`
- WriteWithoutResponse: `0000ae01-0000-1000-8000-00805f9b34fb`
- Notify: `0000ae02-0000-1000-8000-00805f9b34fb`
- Register query: `9AAA03`, 2-byte register code, `0001`, CRC. The switch mask
  query is `9AAA0300120001C61C`.
- Status: exactly 11 bytes, `9AAA0300120201`, 2-byte big-endian disable
  mask, CRC-16/MODBUS with high byte first.
- Write body: `9AAA10001200010201`, 2-byte mask, same CRC.
- ACK: `9AAA10001200010599`. Explicitly **not status** and never `0x0599`.

ACKs, unrelated headers, corrupt CRCs, truncations and concatenated frames do not
update state. Notifications are not buffered between queries. Each query uses a
new connection and callback closure, drains subscription-time traffic for 200 ms,
and accepts only callbacks arriving after its query-write await has returned.
Control uses a separate subscribed connection and waits for the exact ACK before
disconnecting. Verification uses another newly connected query, so queued control
or earlier query notifications cannot fulfill the verification waiter. Readback
must match the complete mask, not just the requested port.

### Important unverified freshness boundary

This reverse-engineered protocol has **no transaction ID or device timestamp**.
No client can cryptographically or causally prove an arbitrarily delayed,
identical unsolicited frame is a query response. Connection isolation and the
post-write callback gate reject known queued/in-flight stale cases; they are not
an on-wire correlation guarantee. The conservative gate can discard a legitimate
response arriving *during* the BLE write await, especially on a proxy. In that
case the operation times out rather than accepting ambiguous state. This timing
must be validated on the intended HA/proxy route before production enablement.
Do not weaken the barrier silently to make a test pass.

The device protocol is also not compare-and-swap: an external app changing bits
between the fresh read and absolute write can race us. Close other controllers.
A retained global shutdown bit may affect physical USB output even when a USB's
own disable bit is clear; the integration preserves rather than interprets it.
Switch state represents protocol disable bits, not measured voltage delivery.
Power sensors are separate register readings reported by the charger.

## Tests

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/python -m pytest -q --cov=custom_components.baseus_gan240 --cov-report=term-missing
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

Tests cover known physical protocol fixtures, every 16-bit mask for both
operations on all four ports, ACK exclusion, CRC/header/length checks, stale
callbacks at subscription and while a query write is in flight, old-connection
callback isolation, timeouts, concurrent operations, uncertain-write behavior,
no-op reads, cancellation/unload, fresh state after uncertain writes, HA flow
validation, switch availability, telemetry decoding, multi-register reads over one
connection, sensor creation, reload cleanup and redacted diagnostics. Release
v0.1.1 was live-verified through an ESPHome proxy on all four switches; telemetry
support in v0.2.0 retains synthetic coverage until its release validation.

## Sources checked 2026-09-07

- https://developers.home-assistant.io/docs/core/bluetooth/api/
- https://developers.home-assistant.io/docs/config_entries_index/
- https://developers.home-assistant.io/docs/creating_integration_manifest/
- https://bleak-retry-connector.readthedocs.io/en/latest/usage.html
- https://raw.githubusercontent.com/home-assistant/core/2026.9.0/homeassistant/components/bluetooth/manifest.json

Protocol behavior was derived from charger GATT observations and validated
against the frame fixtures in the test suite. Recorded example masks are not
assumed to describe any current device state.
