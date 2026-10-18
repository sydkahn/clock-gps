# Changelog

All notable changes to Clock GPS are recorded here. The project follows the
phased plan in `SPECIFICATION.md`.

## [0.1.0] - Phase 1: repository and safe foundation

### Added

- Repository layout for device code, host tools, tests, and documentation.
- `.gitignore` that excludes real credentials while allowing
  `credentials.example.py`.
- `device/credentials.example.py` with placeholders only.
- Minimal application entry point: `device/boot.py`, `device/main.py`,
  `device/version.py`.
- `device/config.py` with configuration and credential validation that never
  exposes secret values.
- `device/clock/time_service.py`, a hardware-independent timekeeping
  interface ready for NTP and GPS sources.
- `device/sensors/base.py` (common sensor interface) and
  `device/sensors/manager.py` (failure-isolating sensor manager).
- Import-safe placeholder modules for Phase 2–7 areas: network, power, and
  updates.
- Host-side placeholder tools `tools/deploy.py` and `tools/monitor.py`.
- Host-side tests (standard library only) for configuration validation,
  timekeeping, sensor failure isolation, and Git credential exclusion.
- Documentation: `README.md` and `docs/` (HARDWARE, INSTALLATION, OTA,
  POWER, MQTT).

### Notes

- No firmware was installed and the ESP32 was not connected, flashed, or
  modified.
- No sensor model was assumed; the weather sensor remains an open question.
