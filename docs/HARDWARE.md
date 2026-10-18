# Hardware

## Confirmed

- **MCU:** Original ESP32 family, chip `ESP32-D0WDQ6`, revision 1.0.
- **Flash:** 4 MB detected.
- **Firmware:** MicroPython v1.29.0 (installed on the board by the owner).
- **Epoch:** 2000-01-01 UTC. `time.gmtime(0)` returned
  `(2000, 1, 1, 0, 0, 0, 5, 1)`, so `time.time()` counts seconds since 2000,
  not since 1970. Convert to Unix time explicitly (see `docs/INSTALLATION.md`
  and `device/clock/time_service.py`).
- **Wi-Fi:** connects successfully; `ntptime.settime()` succeeds against
  `pool.ntp.org` and `time.gmtime()` returns the correct UTC date.
- **USB serial:** observed as `COM6` during initial inspection. COM port
  numbers change between connections, so host tools must detect the port at
  runtime and must never hard-code `COM6`.
- **Radios:** Wi-Fi and Bluetooth are available on the chip. Bluetooth is not
  a requirement unless a future feature needs it.
- **Weather sensor:** Bosch **BME280** (temperature, pressure, and humidity),
  connected over I2C and tested successfully on the ESP32.
  - SDA: GPIO 16
  - SCL: GPIO 17
  - I2C address: `0x76` (value `0x77` is accepted as an alternative; the
    driver checks the chip-id register, `0x60`, before use)

## Not yet confirmed (do not guess)

The following are open questions from `SPECIFICATION.md` section 14. No driver
or hardware assumption should be made until each is confirmed:

1. GPS receiver model and connection (for example UART).
2. Display hardware, and whether it must remain continuously visible.
3. Battery chemistry, capacity, charging/protection circuitry, and voltage
   regulation. Whether the battery is backup-only or must run the device
   continuously is also undecided.
4. Whether an external RTC is required to retain time through power loss.
5. Which tilt and distance sensors will be used and their electrical
   interfaces.

The former open question about the "380 weather chip" is resolved: the
weather sensor is a BME280 (see **Confirmed** above). `SPECIFICATION.md`
section 14 is unchanged, as required.

## Safety

- Do not connect a battery until its chemistry, protection, and regulation
  are confirmed. The development board's USB connector or regulator is not
  assumed to include safe battery charging.
- Do not flash, erase, or modify the board without an explicit step and user
  approval.
