# Clock GPS --- Project Specification

**Document status:** Consolidated draft v0.1\
**Project owner:** Syd Kahn (`sydkahn`)\
**GitHub repository:** `sydkahn/clock-gps`\
**Target development computer:** Lucy (Windows)\
**Local project directory:** `C:\Users\Bob\Projects\clock-gps`\
**Target board:** Original ESP32, chip `ESP32-D0WDQ6`, revision 1.0\
**Detected flash:** 4 MB\
**Initial USB serial port:** `COM6` (may change between connections)\
**Firmware and application language:** MicroPython

------------------------------------------------------------------------

## 1. Purpose and Scope

Clock GPS is a modular, low-power ESP32 project. It begins as a clock
using network time and a weather sensor, and is intended to grow to
support GPS time, additional sensor modules, MQTT commands, and future
home-automation and voice-assistant integrations.

The project will be developed on Lucy using OpenCode with the selected
DeepSeek model as a development assistant. The AI model is a
development-time tool; the ESP32 application must not depend on a cloud
AI service at runtime.

This specification is the source of truth for implementation.
Development must proceed in small, testable phases. Do not flash or
erase the board, overwrite existing firmware, or make irreversible
hardware changes without an explicit step and user approval.

## 2. Goals

1.  Use MicroPython on the original ESP32.
2.  Support application updates over Wi-Fi (application OTA).
3.  Keep secrets in a separate local credentials file excluded from Git.
4.  Use NTP initially for time synchronization, with a modular path to
    GPS time later.
5.  Integrate the intended weather sensor after its exact model is
    confirmed.
6.  Support future sensor modules, including tilt/motion and distance
    sensors.
7.  Publish sensor readings and device status to Node-RED on a Proxmox
    server using MQTT.
8.  Receive requests and commands from MQTT and publish correlated
    responses.
9.  Support battery backup and minimize power consumption with
    appropriate sleep modes.
10. Keep the ESP32 independent of Alexa, Home Assistant, and Node-RED
    APIs. MQTT is the only home-automation interface.
11. Maintain the source and documentation in the GitHub repository
    `sydkahn/clock-gps`.

## 3. Hardware Baseline and Open Hardware Questions

### 3.1 Confirmed hardware

-   Original ESP32 family: `ESP32-D0WDQ6`, revision 1.0.
-   Detected flash capacity: 4 MB.
-   USB serial port during initial inspection: COM6.
-   Wi-Fi and Bluetooth are available on the chip; Bluetooth is not a
    requirement unless a future feature needs it.

COM port numbers can change and must be detected rather than hard-coded
in host tools.

### 3.2 Hardware not yet confirmed

The following must be identified before implementing the corresponding
driver or final hardware design:

-   Exact model and interface of the component described as the "380
    weather chip."
-   GPS receiver model and connection (for example, UART), when GPS is
    added.
-   Clock/display hardware, if a display is part of this build.
-   Battery chemistry, capacity, charging/protection circuitry, and
    power regulation.
-   Whether the design requires an external RTC to retain time through
    extended power loss.
-   Which future tilt and distance sensors will be used.
-   MQTT broker address, port, and authentication details on Proxmox.

Do not guess a sensor model or write a driver based only on the phrase
"380 weather chip." Keep the sensor interface modular until the part is
identified.

## 4. Software and Repository

### 4.1 Development environment

-   Windows development computer: Lucy.
-   Project directory: `C:\Users\Bob\Projects\clock-gps`.
-   MicroPython firmware for the original ESP32.
-   OpenCode is launched from the project directory.
-   Host-side tools should use Python where appropriate and should be
    clearly separated from code that runs on the ESP32.
-   Use Git for version control and commit working milestones.

### 4.2 Proposed repository layout

The final layout may be adjusted to suit MicroPython's import behavior
and the chosen deployment tool, but device code and host tools must
remain clearly separated.

``` text
clock-gps/
├── README.md
├── SPECIFICATION.md
├── CHANGELOG.md
├── .gitignore
├── device/
│   ├── boot.py
│   ├── main.py
│   ├── config.py
│   ├── credentials.example.py
│   ├── clock/
│   │   └── time_service.py
│   ├── network/
│   │   ├── wifi.py
│   │   └── mqtt_client.py
│   ├── sensors/
│   │   ├── manager.py
│   │   └── (one module per supported sensor)
│   ├── power/
│   │   └── power_manager.py
│   └── updates/
│       └── ota.py
├── tools/
│   ├── deploy.py
│   └── monitor.py
├── tests/
└── docs/
    ├── HARDWARE.md
    ├── INSTALLATION.md
    ├── OTA.md
    ├── POWER.md
    └── MQTT.md
```

Do not create empty modules for every hypothetical feature. Add a module
when its phase is implemented. Keep this proposed layout simple and
documented.

## 5. Credentials and Secret Handling

-   The device-side secrets file will be named `credentials.py`.
-   The repository may include `credentials.example.py` with placeholder
    values only.
-   The real `credentials.py` must be excluded by `.gitignore` from the
    first commit.
-   Credentials may include Wi-Fi SSID/password, MQTT broker
    username/password, and other secrets as required.
-   Do not commit Wi-Fi passwords, broker passwords, tokens, private
    keys, or other secrets.
-   Do not print secrets in logs or error messages.
-   The application must handle missing or invalid credentials with a
    useful diagnostic that does not disclose their contents.
-   Verify the Git status and ignored-file behavior before the first
    commit and before every release.

A local credentials file is not a substitute for MQTT broker access
controls. The broker must enforce suitable authentication and topic
permissions. Use TLS where supported by the chosen broker, firmware, and
resource budget; document any limitations.

## 6. Timekeeping

### 6.1 Initial source: NTP

-   Connect to Wi-Fi using local credentials.
-   Synchronize time using NTP.
-   Handle DNS failures, unavailable networks, and NTP timeouts without
    crashing.
-   Record whether time is valid and which source last synchronized it.
-   Avoid frequent, unnecessary NTP requests.
-   Use a configurable retry/backoff policy.
-   Provide a time-service interface that other modules use rather than
    calling NTP directly.

### 6.2 Future source: GPS

-   Add GPS as a later time source after the receiver is identified.
-   Parse and validate GPS time data.
-   Do not treat time as valid merely because serial data is present;
    apply suitable validity checks for the selected receiver/protocol.
-   Allow the time service to select or prioritize GPS and NTP without
    requiring a rewrite of the clock application.
-   Define fallback behavior when GPS reception is unavailable.
-   Document UTC storage and local-time/display conversion separately.

### 6.3 Time retention

Evaluate time accuracy through light sleep, deep sleep, reset, and
complete power loss. Do not assume that application state survives deep
sleep or that the ESP32's internal clock remains accurate indefinitely.
Decide whether an external RTC or resynchronization is required based on
measured needs.

## 7. Modular Sensor Architecture

The application must be a reusable sensor platform, not a monolithic
script.

### 7.1 Sensor modules

Each supported sensor must have a separate module. Potential future
sensors include:

-   Weather/environmental sensor.
-   Tilt or motion sensor.
-   Distance sensor.
-   Battery-voltage/power monitor.
-   Other sensors selected later.

The main application must not contain hardware-specific reading logic. A
new sensor should be addable without rewriting the clock, time service,
MQTT transport, OTA, or power manager.

### 7.2 Common interface

Where appropriate for the sensor, modules should expose a consistent
interface such as:

-   `initialize()` --- configure the sensor and hardware interface.
-   `read()` --- return a structured reading or readings.
-   `status()` --- report availability and errors.
-   `sleep()` / `wake()` --- enter or leave a sensor low-power state
    when supported.

Interrupt-driven sensors may require a different event interface. Sensor
modules return data to the sensor manager; they must not publish to MQTT
directly or print readings as their primary output.

### 7.3 Sensor manager

The sensor manager will:

-   Initialize and track installed sensors.
-   Schedule readings and handle event-driven sensors.
-   Normalize data into documented names and units.
-   Attach timestamps and validity/status information.
-   Isolate sensor errors so one failed sensor does not stop other
    modules.
-   Coordinate sensor operation with the power manager.
-   pass collected data to the communications layer.

Do not invent readings for missing or failed sensors. Use an explicit
unavailable/error status rather than a valid-looking zero.

## 8. MQTT and Node-RED Integration

### 8.1 Sole home-automation interface

MQTT is the only interface between the ESP32 and home-automation
systems. The ESP32 must not depend directly on Alexa, Home Assistant,
Node-RED APIs, or their internal implementations.

Node-RED will run on the Proxmox server and consume telemetry, issue
commands, and coordinate request/response flows. The Proxmox MQTT broker
address is not yet known and must be configured later.

### 8.2 Initial topic proposal

Use a configurable, documented topic structure. Proposed examples:

``` text
clock-gps/<device-id>/telemetry
clock-gps/<device-id>/status
clock-gps/<device-id>/events
clock-gps/<device-id>/commands
clock-gps/<device-id>/config
clock-gps/<device-id>/responses
```

Finalize topic names, QoS, retain behavior, and payload schemas before
implementing the MQTT phase. Avoid retaining one-time commands. Retained
messages may be suitable for current desired configuration, with
explicit versioning and validation.

### 8.3 Telemetry

Publish as appropriate:

-   Sensor readings and units.
-   Measurement timestamp and validity.
-   Device status and error events.
-   Time source and synchronization status.
-   Wi-Fi/MQTT connection state where useful.
-   Battery voltage/charge estimate when hardware supports it.
-   Firmware/application version.

JSON is the initial proposed payload format. Keep it compact and
suitable for MicroPython.

### 8.4 Requests and commands

The device must accept validated MQTT requests for supported operations,
potentially including:

-   Read a sensor now.
-   Report device status/time/battery state.
-   Change supported sampling or reporting intervals.
-   Change supported display settings if a display is installed.
-   Request an application update.

Commands must be validated, bounded, and rejected safely if unsupported
or malformed. Do not permit arbitrary code execution through MQTT. OTA
requests must follow the separate OTA security rules.

### 8.5 Request/response protocol

-   Each query/request must carry a unique request identifier.
-   The response must include the matching identifier, result,
    timestamp, and status.
-   The server must be able to correlate a response with the original
    request.
-   Define timeouts and behavior for unavailable sensors/devices.
-   Handle duplicate message delivery so one-time actions are not
    unintentionally repeated.
-   Distinguish transient commands from persistent desired-state
    configuration.
-   Avoid reporting stale data as current; include the measurement
    timestamp.

### 8.6 Future voice and home automation

In the future, Home Assistant and Alexa may be integrated on the server
side. That is not part of the initial device implementation. Server-side
services can translate a voice question into an MQTT query and turn the
response into a concise spoken answer. The ESP32 remains unaware of the
voice assistant.

Examples of future queries include "What is the temperature?" and "Is
the garage door open?" The latter requires a real door sensor or an
authoritative external data source; Clock GPS must never guess the
state.

## 9. Power, Battery Backup, and Sleep

Battery support and power minimization are core design requirements.
Exact runtime cannot be promised until the board, display/peripherals,
battery, regulator, and workload are measured.

### 9.1 Battery and hardware safety

-   Identify compatible battery chemistry, capacity, charging/protection
    circuitry, and voltage regulation before connecting a battery.
-   Do not assume the development board's USB connector or regulator
    includes safe battery charging.
-   Monitor battery voltage when hardware supports it.
-   Define low-battery and critical-battery behavior.
-   Measure total device current, including regulator, power LED, USB
    interface, display, sensors, and other peripherals---not only ESP32
    chip current.

### 9.2 MicroPython power management

Use supported MicroPython and ESP32 features, including
`machine.lightsleep()` and `machine.deepsleep()` where suitable.

-   Avoid busy loops and unnecessary polling.
-   Disable Wi-Fi/Bluetooth when not needed.
-   Power down sensors and display/backlight when supported and
    appropriate.
-   Schedule sensor readings and NTP synchronization to avoid
    unnecessary wakeups.
-   Use interrupt-driven wake sources for appropriate sensors.
-   Account for deep-sleep reset/restart semantics and restore needed
    state.
-   Coordinate sleep with pending telemetry, commands, and OTA updates.
-   Never intentionally sleep during a critical update write/activation
    step.

### 9.3 MQTT versus sleep

MQTT cannot deliver messages to a device that is asleep and
disconnected. The design must provide configurable operating modes:

1.  **Connected mode:** Maintain Wi-Fi/MQTT for lower-latency commands
    when external power or responsiveness requirements justify it.
2.  **Low-power mode:** Wake on a schedule, connect, retrieve applicable
    pending state/commands, perform work, publish queued data,
    disconnect, and sleep.

A one-second command-check target is desired for evaluation, not a
guaranteed behavior or a fixed design assumption. Reconnecting to
Wi-Fi/MQTT every second may consume more energy than it saves. Measure
current and command latency before choosing a default. Do not implement
a one-second busy polling loop.

The server must account for offline periods. Retained desired state may
be used for settings; transient commands require an explicit
queue/expiry/duplicate policy so stale commands are not executed
unexpectedly.

### 9.4 Power validation

Measure current and responsiveness under representative conditions,
including active work, Wi-Fi/MQTT connected, connection/reconnection,
sensor sampling, light sleep, and deep sleep where applicable. Document
actual battery runtime after selecting the final hardware and workload.

## 10. OTA Updates

### 10.1 Application OTA

Application OTA over Wi-Fi is required. Routine application deployments
should not require USB.

-   Provide a host-side deployment tool.
-   Transfer application files or a versioned package.
-   Validate the package and file contents before activation.
-   Handle interrupted transfers and failed deployments.
-   Keep a known-good version or provide a documented recovery path.
-   Prevent unauthorized updates; authenticate the update operation and
    verify integrity.
-   Coordinate updates with power management and avoid sleep during
    critical operations.
-   Report version and result status through logs/MQTT where
    appropriate.

The exact mechanism must be selected after reviewing the chosen
MicroPython build, filesystem layout, flash constraints, and available
libraries. Do not assume a generic built-in OTA facility exists.

### 10.2 MicroPython firmware OTA

Updating the MicroPython firmware itself over Wi-Fi is a separate, more
demanding feature. Assess whether it is supported by the selected
firmware and partition layout. Do not promise or implement firmware OTA
until its safety, recovery, and flash requirements are confirmed. USB
recovery must remain documented.

## 11. Reliability, Diagnostics, and Security

-   A failed sensor or network connection must not crash unrelated
    subsystems.
-   Use bounded retries and backoff to avoid wasting battery.
-   Provide useful diagnostics without logging secrets.
-   Validate MQTT payloads, ranges, identifiers, and command types.
-   Avoid arbitrary code execution through MQTT.
-   Keep telemetry timestamps and status explicit.
-   Handle stale readings, duplicate requests, network outages, and
    unavailable sensors.
-   Document recovery from failed application deployment and corrupted
    configuration.
-   Do not perform destructive flash operations without explicit user
    approval.

## 12. Testing Strategy

Develop and test in small increments.

-   Unit-test host-side logic and protocol/schema handling where
    possible.
-   Keep hardware-dependent functions behind small interfaces that can
    be tested with fakes/mocks.
-   Test sensor failure isolation.
-   Test MQTT request/response correlation and duplicate handling.
-   Test network loss/recovery.
-   Test sleep/wake and time restoration.
-   Test OTA interruption, invalid packages, and recovery.
-   Test that credentials are ignored by Git.
-   Verify that the device can start with optional sensors absent.
-   Measure actual power and command latency on hardware.

## 13. Development Phases and Acceptance Criteria

### Phase 1 --- Repository and safe foundation

-   Create/connect `sydkahn/clock-gps`.
-   Set up the local directory and Git.
-   Commit this specification and a `.gitignore` that excludes
    credentials.
-   Identify firmware and flash layout before flashing.
-   Decide whether and how to preserve existing firmware.

**Acceptance:** Repository contains specification/documentation and no
secrets; no unapproved destructive operation has occurred.

### Phase 2 --- MicroPython over USB

-   Install the selected firmware only after confirming the correct
    build and recovery plan.
-   Establish REPL access and a minimal application.
-   Document board/port detection and recovery.

**Acceptance:** The ESP32 runs MicroPython reliably and can be monitored
from Lucy.

### Phase 3 --- Wi-Fi and NTP

-   Load local credentials.
-   Connect to Wi-Fi.
-   Synchronize time via NTP.
-   Handle unavailable networks without crashing.

**Acceptance:** Valid time is established when the network is available,
and failure status is explicit otherwise.

### Phase 4 --- MQTT foundation

-   Connect to the configured broker.
-   Publish status and a test telemetry message.
-   Receive and validate a test command.
-   Implement correlated request/response.

**Acceptance:** Node-RED or an MQTT test client can receive telemetry,
issue a query, and correlate the response.

### Phase 5 --- Application OTA

-   Implement the host deployment tool and device updater.
-   Test valid, invalid, and interrupted updates.
-   Document rollback/recovery.

**Acceptance:** Application changes can be deployed over Wi-Fi and
failed updates do not permanently brick the application.

### Phase 6 --- Modular sensor framework

-   Implement the sensor manager and the first confirmed sensor driver.
-   Add later sensors independently.
-   Publish readings through the shared MQTT layer.

**Acceptance:** Adding or failing one sensor does not require rewriting
the main application or break other sensors.

### Phase 7 --- Power management and battery validation

-   Implement coordinated scheduling and sleep modes.
-   Measure current and latency.
-   Choose sensible connected/low-power defaults from measured results.

**Acceptance:** Power modes work as documented and measured data
supports runtime estimates.

### Phase 8 --- GPS time

-   Add the selected GPS receiver and driver.
-   Integrate it through the time-service interface.
-   Test fallback behavior.

**Acceptance:** GPS can provide valid time without redesigning the rest
of the application.

### Phase 9 --- Server-side and future integrations

-   Document Node-RED flows and MQTT contract.
-   Add optional Home Assistant/Alexa server-side integration later if
    desired.
-   Keep all such integrations outside the ESP32 firmware.

**Acceptance:** New server-side clients can use the MQTT contract
without requiring a change to the device's core architecture.

## 14. Unresolved Decisions

These are deliberate open questions, not assumptions to be filled in by
the coding agent:

1.  Exact "380 weather chip" model and interface.
2.  Exact GPS receiver and interface.
3.  Display hardware and whether it must remain continuously visible.
4.  Battery chemistry/capacity, charging/protection, and whether battery
    is backup-only or must run the device continuously.
5.  Whether an external RTC is needed.
6.  Proxmox MQTT broker address, port, authentication, and TLS setup.
7.  Desired default telemetry intervals and acceptable query latency.
8.  Whether one-second command responsiveness is required in connected
    mode only or is merely an experiment.
9.  Final MQTT topics, QoS, retain behavior, and command expiry/queue
    semantics.
10. Exact application OTA implementation and whether firmware OTA is
    feasible.
11. Future sensor models and their electrical interfaces.

The coding agent must ask before making decisions that affect safety,
erase existing firmware, expose credentials, or materially change this
architecture. For ordinary implementation details, it should propose a
choice, document it, and proceed only within the agreed requirements.
