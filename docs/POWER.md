# Power, battery backup, and sleep

Battery support and power minimization are core requirements. Exact runtime
cannot be promised until the board, display/peripherals, battery, regulator,
and workload are measured.

## Status

Planning only. Power management is Phase 7. No battery hardware has been
connected or assumed.

## Battery and hardware safety

- Chemistry, capacity, charging/protection circuitry, and voltage regulation
  must be identified before connecting a battery.
- The development board's USB connector or regulator is not assumed to
  include safe battery charging.
- Monitor battery voltage only when hardware supports it.
- Define low-battery and critical-battery behavior.
- Measure total device current (regulator, power LED, USB interface, display,
  sensors, and other peripherals), not only ESP32 chip current.

## MicroPython power management

Use `machine.lightsleep()` and `machine.deepsleep()` where suitable:

- Avoid busy loops and unnecessary polling.
- Disable Wi-Fi/Bluetooth when not needed.
- Power down sensors and display/backlight when supported.
- Schedule readings and NTP sync to avoid unnecessary wakeups.
- Use interrupt-driven wake sources for appropriate sensors.
- Account for deep-sleep reset semantics and restore needed state.
- Coordinate sleep with pending telemetry, commands, and OTA; never sleep
  during a critical update write.

## Operating modes

1. **Connected mode:** keep Wi-Fi/MQTT up for lower-latency commands when
   external power or responsiveness justifies it.
2. **Low-power mode:** wake on a schedule, connect, retrieve applicable
   state/commands, work, publish queued data, disconnect, and sleep.

A one-second command-check target is an experiment to evaluate, not a design
assumption. Do not implement a one-second busy polling loop; measure current
and latency before choosing defaults.
