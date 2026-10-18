# Hardware

## Confirmed

- **MCU:** Original ESP32 family, chip `ESP32-D0WDQ6`, revision 1.0.
- **Flash:** 4 MB detected.
- **USB serial:** observed as `COM6` during initial inspection. COM port
  numbers change between connections, so host tools must detect the port at
  runtime and must never hard-code `COM6`.
- **Radios:** Wi-Fi and Bluetooth are available on the chip. Bluetooth is not
  a requirement unless a future feature needs it.

## Not yet confirmed (do not guess)

The following are open questions from `SPECIFICATION.md` section 14. No driver
or hardware assumption should be made until each is confirmed:

1. Exact model and interface of the component described as the "380 weather
   chip". The phrase is not sufficient to identify a part; the sensor
   interface stays modular until the model is known.
2. GPS receiver model and connection (for example UART).
3. Display hardware, and whether it must remain continuously visible.
4. Battery chemistry, capacity, charging/protection circuitry, and voltage
   regulation. Whether the battery is backup-only or must run the device
   continuously is also undecided.
5. Whether an external RTC is required to retain time through power loss.
6. Which tilt and distance sensors will be used and their electrical
   interfaces.

## Safety

- Do not connect a battery until its chemistry, protection, and regulation
  are confirmed. The development board's USB connector or regulator is not
  assumed to include safe battery charging.
- Do not flash, erase, or modify the board without an explicit step and user
  approval.
