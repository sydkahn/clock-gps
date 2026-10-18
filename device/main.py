"""Clock GPS application entry point.

Phase 1 provides a minimal, safe startup path only. It loads and validates
configuration, reports the application version, and then returns. Wi-Fi,
NTP, MQTT, sensors, power management, and OTA are added in later phases and
must not be wired in here until their phase is implemented.

This module is intentionally free of hardware-specific code so that the
application stays a reusable sensor platform rather than a monolith.
"""

import config
import version


def start():
    """Validate configuration and log a safe startup banner.

    Returns the validated ``config.Config`` on success, or ``None`` when
    configuration is missing or invalid. No secrets are printed.
    """
    try:
        app_config = config.load()
    except config.ConfigurationError as exc:
        print("[clock-gps] configuration error:", exc)
        return None

    print("[clock-gps] %s starting (device %s)" % (version.__version__, app_config.device_id))
    print("[clock-gps] foundation ready; networking, time, MQTT, sensors, "
          "power, and OTA arrive in later phases")
    return app_config


def main():
    """MicroPython calls this implicitly when ``main.py`` finishes loading."""
    return start()


if __name__ == "__main__":
    main()
