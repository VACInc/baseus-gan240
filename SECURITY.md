# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
**Security > Report a vulnerability** form on this repository. If that form
is unavailable, open an issue asking for a private contact and do not include
exploit details, Bluetooth addresses or logs in the public issue.

Include the integration version, Home Assistant version, the Bluetooth path
(local adapter or ESPHome proxy) and steps to reproduce.

## Out of scope

The charger's Bluetooth protocol is unauthenticated by design of the device:
any nearby BLE client can control it. That is a property of the hardware, not
a vulnerability in this integration. See "Security model" in the README.
