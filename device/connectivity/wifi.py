"""Wi-Fi connectivity.

Connects the ESP32 station interface using credentials from the existing
configuration system (``config.py`` loads the local, git-ignored
``credentials.py``). Passwords and other secrets are never printed and never
appear in status or error messages.

The MicroPython-only ``network`` module is imported lazily, so this module can
be imported and unit-tested on the development computer. The
``network_module``, ``clock`` and ``sleep`` constructor arguments allow tests
to inject fakes.
"""

import config

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_ERROR = "error"


def _default_clock():
    """Return seconds from a monotonic clock (MicroPython or host)."""
    import time
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms() / 1000.0
    return time.monotonic()


def _default_sleep(seconds):
    import time
    time.sleep(seconds)


def _describe_error(exc):
    """Return a secret-free one-line description of *exc*."""
    text = str(exc)
    if text:
        return "%s: %s" % (type(exc).__name__, text)
    return type(exc).__name__


class WifiManager:
    """Manages the station (STA) Wi-Fi connection and reports its status."""

    def __init__(self, credentials, timeout_s=20, poll_interval_s=0.25,
                 network_module=None, clock=None, sleep=None):
        self._credentials = credentials
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._network_module = network_module
        self._clock = clock if clock is not None else _default_clock
        self._sleep = sleep if sleep is not None else _default_sleep
        self._wlan = None
        self._state = STATE_DISCONNECTED
        self._last_error = None
        self._ip = None

    # -- lazy hardware import ------------------------------------------
    def _get_network_module(self):
        if self._network_module is None:
            import network
            self._network_module = network
        return self._network_module

    # -- credentials ----------------------------------------------------
    def _ssid(self):
        return getattr(self._credentials, "wifi_ssid", None)

    def _has_credentials(self):
        if self._credentials is None:
            return False
        if config.is_placeholder(self._ssid()):
            return False
        if config.is_placeholder(getattr(self._credentials, "wifi_password", None)):
            return False
        return True

    # -- connection -----------------------------------------------------
    def connect(self):
        """Connect to the configured network. Returns True on success.

        Never raises for expected network failures; the reason is stored in a
        secret-free status message.
        """
        self._last_error = None
        self._ip = None
        if not self._has_credentials():
            self._state = STATE_ERROR
            self._last_error = "no Wi-Fi credentials configured"
            return False

        self._state = STATE_CONNECTING
        try:
            network = self._get_network_module()
            wlan = network.WLAN(network.STA_IF)
            self._wlan = wlan
            wlan.active(True)
            if not wlan.isconnected():
                wlan.connect(self._ssid(),
                             getattr(self._credentials, "wifi_password", None))
                if not self._wait_for_connection(wlan):
                    return False
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            self._state = STATE_ERROR
            self._last_error = _describe_error(exc)
            self._safe_disconnect()
            return False

        self._state = STATE_CONNECTED
        self._ip = self._read_ip(wlan)
        self._last_error = None
        return True

    def _wait_for_connection(self, wlan):
        deadline = self._clock() + self._timeout_s
        while not wlan.isconnected():
            if self._clock() >= deadline:
                self._state = STATE_ERROR
                self._last_error = ("timed out after %ss waiting for Wi-Fi"
                                    % self._timeout_s)
                self._safe_disconnect()
                return False
            self._sleep(self._poll_interval_s)
        return True

    def _read_ip(self, wlan):
        try:
            ifconfig = wlan.ifconfig()
        except Exception:  # noqa: BLE001
            return None
        if ifconfig:
            return ifconfig[0]
        return None

    def _safe_disconnect(self):
        wlan = self._wlan
        if wlan is None:
            return
        try:
            wlan.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def disconnect(self):
        """Disconnect and release the station interface."""
        self._safe_disconnect()
        try:
            if self._wlan is not None:
                self._wlan.active(False)
        except Exception:  # noqa: BLE001
            pass
        self._state = STATE_DISCONNECTED
        self._ip = None

    def is_connected(self):
        wlan = self._wlan
        if wlan is None:
            return False
        try:
            return bool(wlan.isconnected())
        except Exception:  # noqa: BLE001
            return False

    def ip_address(self):
        return self._ip

    def status(self):
        """Return a secret-free status snapshot for logs and telemetry."""
        return {
            "state": self._state,
            "connected": self._state == STATE_CONNECTED,
            "ip": self._ip,
            "credentials_configured": self._has_credentials(),
            "last_error": self._last_error,
        }


def from_config(app_config, **kwargs):
    """Create a WifiManager from a ``config.Config`` and its credentials."""
    return WifiManager(app_config.credentials, **kwargs)
