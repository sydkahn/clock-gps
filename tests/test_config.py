"""Tests for device/config.py configuration and credential validation.

These run on the development computer and use only the standard library.
"""

import sys
import types
import unittest

import _support  # noqa: F401  (adjusts sys.path so device/ modules import)
import config


class PlaceholderTests(unittest.TestCase):
    def test_placeholder_detection(self):
        self.assertTrue(config.is_placeholder(None))
        self.assertTrue(config.is_placeholder("<your-wifi-ssid>"))
        self.assertTrue(config.is_placeholder("   "))
        self.assertFalse(config.is_placeholder("MyNetwork"))
        self.assertFalse(config.is_placeholder(1883))


class DeviceIdTests(unittest.TestCase):
    def test_valid_ids(self):
        for value in ("clock-gps-01", "esp32_a", "abc123"):
            self.assertIsNone(config.validate_device_id(value), value)

    def test_empty_and_invalid_ids(self):
        self.assertIsNotNone(config.validate_device_id(""))
        self.assertIsNotNone(config.validate_device_id("has space"))
        self.assertIsNotNone(config.validate_device_id("bad/slash"))


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        app_config = config.Config()
        self.assertEqual([], app_config.validate())
        self.assertTrue(app_config.is_valid())

    def test_invalid_device_id_is_reported(self):
        problems = config.Config(device_id="bad/id").validate()
        self.assertTrue(any("device_id" in p for p in problems))

    def test_placeholder_ntp_host_is_reported(self):
        problems = config.Config(ntp_host="<ntp-host>").validate()
        self.assertTrue(any("ntp_host" in p for p in problems))

    def test_intervals_must_be_large_enough(self):
        problems = config.Config(telemetry_interval_s=1).validate()
        self.assertTrue(any("telemetry_interval_s" in p for p in problems))

    def test_non_integer_interval_is_reported(self):
        problems = config.Config(ntp_timeout_s="soon").validate()
        self.assertTrue(any("ntp_timeout_s" in p for p in problems))

    def test_topic_composition(self):
        app_config = config.Config(device_id="clock-gps-01")
        self.assertEqual("clock-gps/clock-gps-01/telemetry",
                         app_config.topic("telemetry"))


class CredentialTests(unittest.TestCase):
    def test_placeholder_credentials_are_rejected(self):
        credentials = config.Credentials.from_module(types.SimpleNamespace())
        problems = credentials.validate()
        self.assertTrue(any("WIFI_SSID" in p for p in problems))
        self.assertTrue(any("WIFI_PASSWORD" in p for p in problems))

    def test_credentials_error_does_not_leak_values(self):
        credentials = config.Credentials(
            wifi_ssid="<placeholder>", wifi_password="<placeholder>")
        problems = credentials.validate()
        joined = "; ".join(problems)
        self.assertNotIn("<placeholder>", joined)

    def test_complete_credentials_pass(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2")
        self.assertEqual([], credentials.validate())

    def test_mqtt_optional_until_configured(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2")
        self.assertFalse(credentials.has_mqtt())

    def test_mqtt_detected_when_host_set(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2",
            mqtt_host="broker.local")
        self.assertTrue(credentials.has_mqtt())
        self.assertEqual([], credentials.validate())

    def test_invalid_mqtt_port_is_reported(self):
        credentials = config.Credentials(
            wifi_ssid="MyNetwork", wifi_password="hunter2",
            mqtt_host="broker.local", mqtt_port=70000)
        self.assertTrue(any("MQTT_PORT" in p for p in credentials.validate()))


class LoadTests(unittest.TestCase):
    def test_load_with_valid_module(self):
        module = types.SimpleNamespace(
            WIFI_SSID="MyNetwork", WIFI_PASSWORD="hunter2")
        app_config = config.load(credentials_module=module)
        self.assertIsNotNone(app_config.credentials)
        self.assertEqual("MyNetwork", app_config.credentials.wifi_ssid)

    def test_load_with_incomplete_module_raises_without_values(self):
        module = types.SimpleNamespace(WIFI_SSID="<ssid>", WIFI_PASSWORD="<pw>")
        with self.assertRaises(config.ConfigurationError) as ctx:
            config.load(credentials_module=module)
        self.assertNotIn("<pw>", str(ctx.exception))

    def test_missing_credentials_module_reports_helpful_error(self):
        saved = sys.modules.get("credentials", "MISSING")
        sys.modules["credentials"] = None  # forces ImportError on import
        try:
            with self.assertRaises(config.ConfigurationError) as ctx:
                config.load_credentials()
            self.assertIn("credentials.example.py", str(ctx.exception))
        finally:
            if saved == "MISSING":
                sys.modules.pop("credentials", None)
            else:
                sys.modules["credentials"] = saved


if __name__ == "__main__":
    unittest.main()
