# MQTT and Node-RED integration

MQTT is the only home-automation interface between the ESP32 and external
systems. The device must not depend on Alexa, Home Assistant, or Node-RED
APIs. Broker details for the Proxmox server are not yet known.

## Status

Planning only. MQTT is Phase 4 and nothing is implemented. This document
records the proposed contract to be finalized before implementation.

## Proposed topics

```text
clock-gps/<device-id>/telemetry
clock-gps/<device-id>/status
clock-gps/<device-id>/events
clock-gps/<device-id>/commands
clock-gps/<device-id>/config
clock-gps/<device-id>/responses
```

`<device-id>` comes from `device/config.py` (`Config.device_id`). Topic names,
QoS, retain behavior, and payload schemas must be finalized before Phase 4.

## Guidelines

- Payloads are compact JSON, suitable for MicroPython.
- Telemetry carries sensor readings with units, the measurement timestamp,
  validity, time source, connection state, and firmware version.
- Do not retain one-time commands. Retained messages may suit desired-state
  configuration, with explicit versioning and validation.
- Every request carries a unique request identifier; responses echo it with a
  result, timestamp, and status so the server can correlate them.
- Validate payloads, ranges, identifiers, and command types. Never allow
  arbitrary code execution through MQTT.
- Handle duplicate delivery so one-time actions are not repeated, and never
  report stale data as current.

## Credentials

Broker host, port, username, and password come from the git-ignored
`device/credentials.py`. Access controls on the broker are required as well;
a local secrets file is not a substitute. Use TLS where the broker, firmware,
and resource budget allow, and document any limitation.
