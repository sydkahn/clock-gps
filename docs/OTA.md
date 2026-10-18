# Application OTA (over the air)

Application OTA over Wi-Fi is a required feature (Phase 5). Routine
application deployments should not require USB. Nothing is implemented yet,
and no code in this repository writes to flash.

## Status

Planning only. The mechanism will be chosen after reviewing the selected
MicroPython build, filesystem layout, 4 MB flash constraints, and available
libraries. Do not assume a generic built-in OTA facility exists.

## Required properties

- Host-side deployment tool (`tools/deploy.py`).
- Transfer application files or a versioned package.
- Validate the package and file contents before activation.
- Handle interrupted transfers and failed deployments.
- Keep a known-good version or provide a documented recovery path.
- Authenticate the update operation and verify integrity; prevent
  unauthorized updates.
- Coordinate with power management and never sleep during a critical
  write/activation step.
- Report version and result through logs and MQTT where appropriate.

## Firmware OTA

Updating the MicroPython firmware itself is a separate, more demanding
feature. It is not promised or implemented until its safety, recovery, and
flash requirements are confirmed. USB recovery must remain documented.

## Recovery

Documented recovery for a failed application deployment and corrupted
configuration is required before this phase is considered complete. Board
recovery over USB is described in `docs/INSTALLATION.md`.
