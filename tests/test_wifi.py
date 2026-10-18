"""Tests for device/connectivity/wifi.py.

Uses a fake ``network`` module and a fake clock, so no Wi-Fi hardware is
required.
"""

import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
import config
from connectivity.wifi import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_ERROR,
    WifiManager,
    from_config,
)


class FakeClock:
    """A monotonic-ish clock that advances by a fixed step on each call."""

    def __init__(self, step=1.0, start=0.0):
        self.value = start
        self.step = step

    def __call__(self):
        current = self.value
        self.value += self.step
        return current


class FakeWLAN:
    def __init__(self, mode, connects=True, initially_connected=False,
                 error=None):
        self.mode = mode
        self._connected = initially_connected
        self._connects = connects
        self._error = error
        self.connect_args = None
        self.disconnect_calls = 0
        self.active_values = []

    def active(self, value=None):
        if value is not None:
            self.active_values.append(value)
        return True

    def isconnected(self):
        return self._connected

    def connect(self, ssid, psk):
        if self._error is not None:
            raise self._error
        self.connect_args = (ssid, psk)
        self._connected = self._connects

    def disconnect(self):
        self.disconnect_calls += 1
        self._connected = False

    def ifconfig(self):
        return ("10.0.0.203", "255.255.255.0", "10.0.0.1", "10.0.0.1")


class FakeNetwork:
    STA_IF = 0

    def __init__(self, wlan):
        self._wlan = wlan

    def WLAN(self, mode):
        return self._wlan


def working_credentials():
    return config.Credentials(wifi_ssid="MyNetwork", wifi_password="hunter2")


def make_manager(wlan, **kwargs):
    sleep_calls = []

    def sleep(seconds):
        sleep_calls.append(seconds)

    manager = WifiManager(
        kwargs.pop("credentials", working_credentials()),
        network_module=FakeNetwork(wlan),
        clock=kwargs.pop("clock", FakeClock(step=1.0, start=0.0)),
        sleep=sleep,
        **kwargs
    )
    return manager, sleep_calls


class WifiManagerTests(unittest.TestCase):
    def test_successful_connection(self):
        wlan = FakeWLAN(0)
        manager, _ = make_manager(wlan)

        self.assertTrue(manager.connect())
        self.assertEqual(("MyNetwork", "hunter2"), wlan.connect_args)
        self.assertEqual("10.0.0.203", manager.ip_address())

        status = manager.status()
        self.assertTrue(status["connected"])
        self.assertEqual(STATE_CONNECTED, status["state"])
        self.assertTrue(status["credentials_configured"])
        self.assertIsNone(status["last_error"])

    def test_timeout_is_reported_safely(self):
        wlan = FakeWLAN(0, connects=False)
        manager, _ = make_manager(
            wlan, timeout_s=3, clock=FakeClock(step=1.0, start=0.0))

        self.assertFalse(manager.connect())
        status = manager.status()
        self.assertEqual(STATE_ERROR, status["state"])
        self.assertIn("timed out", status["last_error"])
        self.assertGreaterEqual(wlan.disconnect_calls, 1)

    def test_password_never_appears_in_status(self):
        wlan = FakeWLAN(0, connects=False)
        manager, _ = make_manager(wlan, timeout_s=2)
        manager.connect()
        self.assertNotIn("hunter2", str(manager.status()))

    def test_missing_credentials_reports_error(self):
        manager = WifiManager(None, network_module=FakeNetwork(FakeWLAN(0)))
        self.assertFalse(manager.connect())
        status = manager.status()
        self.assertEqual(STATE_ERROR, status["state"])
        self.assertFalse(status["credentials_configured"])

    def test_placeholder_credentials_are_reported(self):
        manager = WifiManager(
            config.Credentials(wifi_ssid="<ssid>", wifi_password="<pw>"),
            network_module=FakeNetwork(FakeWLAN(0)),
        )
        self.assertFalse(manager.connect())
        self.assertEqual(STATE_ERROR, manager.status()["state"])

    def test_connect_exception_is_handled(self):
        wlan = FakeWLAN(0, error=OSError("connection failed"))
        manager, _ = make_manager(wlan)

        self.assertFalse(manager.connect())
        status = manager.status()
        self.assertEqual(STATE_ERROR, status["state"])
        self.assertIn("OSError", status["last_error"])

    def test_already_connected_skips_connect(self):
        wlan = FakeWLAN(0, initially_connected=True)
        manager, _ = make_manager(wlan)

        self.assertTrue(manager.connect())
        self.assertIsNone(wlan.connect_args)

    def test_disconnect_resets_state(self):
        wlan = FakeWLAN(0)
        manager, _ = make_manager(wlan)
        manager.connect()

        manager.disconnect()
        self.assertEqual(STATE_DISCONNECTED, manager.status()["state"])
        self.assertFalse(manager.is_connected())

    def test_from_config_uses_credentials(self):
        app_config = config.Config()
        app_config.credentials = working_credentials()

        manager = from_config(
            app_config,
            network_module=FakeNetwork(FakeWLAN(0)),
            clock=FakeClock(),
            sleep=lambda seconds: None,
        )
        self.assertTrue(manager.connect())


if __name__ == "__main__":
    unittest.main()
