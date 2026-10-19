"""Clock GPS application entry point.

Phase 6 integration: load the validated configuration and credentials,
connect Wi-Fi, synchronize time through the shared time service, then read
the BME280 weather sensor through the sensor manager and the weather module
and report a readable summary on a configurable interval.

A read-only web dashboard (``connectivity.dashboard``) can also serve a small
status page from the same loop. It is handed each reading after it is taken and
is serviced during the wait between readings, so it never reads a sensor itself
and never blocks the reading schedule; a page "refresh" request is queued back
to this loop rather than triggering a second reading path.

Hardware access stays inside the sensor, connectivity, and time modules; this
file only coordinates them and never imports ``machine``, ``network``, or
``ntptime`` directly, so it can be imported and unit-tested on the
development computer with injected fakes. MQTT, a display, GPS, and power
management are later phases and are deliberately not wired in here.
"""

import config
import version
from clock.time_service import TimeService, format_timestamp
from connectivity.dashboard import Dashboard
from connectivity.wifi import from_config as wifi_from_config
from sensors.base import STATUS_OK
from sensors.bme280 import (DEFAULT_ADDRESS as BME280_ADDRESS,
                            DEFAULT_SCL_PIN as BME280_SCL_PIN,
                            DEFAULT_SDA_PIN as BME280_SDA_PIN)
from sensors.manager import SensorManager
from sensors.weather import PressureHistoryStore, WeatherSensor

#: Name used by the weather sensor module; the loop reports this record.
WEATHER_SENSOR_NAME = "weather"

#: Shown in place of a timestamp when the clock is not synchronized.
TIME_NOT_SET = "TIME NOT SET"

# Retry backoff (seconds) so an unavailable Wi-Fi network or NTP server does
# not become a rapid retry loop. The reading interval itself comes from
# ``config.telemetry_interval_s``.
DEFAULT_WIFI_RETRY_INTERVAL_S = 60
DEFAULT_NTP_RETRY_INTERVAL_S = 60


def _default_sleep(seconds):
    import time
    time.sleep(seconds)


def _default_clock():
    """Return monotonic-ish seconds (MicroPython or host)."""
    import time
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms() / 1000.0
    return time.monotonic()


def format_reading(reading):
    """Return a readable single-line summary of a weather *reading*.

    Pure function: no hardware or clock access. Reports temperature in
    Fahrenheit, relative humidity, station pressure and estimated sea-level
    pressure in inHg, and the pressure-trend status. Station and sea-level
    pressures are reported separately and never substituted for one another,
    and the sea-level value is always marked as an estimate.
    """
    trend = reading.get("pressure_trend", "waiting_for_history")
    delta = reading.get("pressure_trend_delta_hpa")
    if delta is None:
        trend_text = str(trend)
    else:
        trend_text = "%s (%+.2f hPa)" % (trend, delta)
    return ("temp %.1f F | humidity %.1f %% | station %.3f inHg | "
            "sea-level %.3f inHg (estimated) | trend %s"
            % (reading["temperature_f"], reading["humidity_pct"],
               reading["pressure_station_inhg"],
               reading["pressure_sea_level_inhg"], trend_text))


class ClockGpsApp:
    """Coordinates configuration, connectivity, time, and the sensor loop."""

    def __init__(self, app_config, wifi=None, time_service=None,
                 sensor_manager=None, dashboard=None, clock=None, sleep=None,
                 interval_s=None,
                 wifi_retry_interval_s=DEFAULT_WIFI_RETRY_INTERVAL_S,
                 ntp_retry_interval_s=DEFAULT_NTP_RETRY_INTERVAL_S):
        self.config = app_config
        self._time = time_service if time_service is not None else TimeService()
        self._wifi = wifi if wifi is not None else wifi_from_config(app_config)
        if sensor_manager is None:
            sensor_manager = SensorManager(time_service=self._time)
            sensor_manager.register(WeatherSensor(
                config=app_config, time_service=self._time,
                address=BME280_ADDRESS, sda_pin=BME280_SDA_PIN,
                scl_pin=BME280_SCL_PIN, store=PressureHistoryStore()))
        self._manager = sensor_manager
        self._clock = clock if clock is not None else _default_clock
        self._sleep = sleep if sleep is not None else _default_sleep
        if interval_s is None:
            interval_s = app_config.telemetry_interval_s
        self._interval_s = int(interval_s)
        self._wifi_retry_interval_s = wifi_retry_interval_s
        self._ntp_retry_interval_s = ntp_retry_interval_s
        self._next_wifi_retry = None
        self._next_ntp_attempt = None
        if dashboard is None:
            dashboard = Dashboard(
                device_id=app_config.device_id,
                version=version.__version__,
                wifi=self._wifi,
                time_service=self._time,
                port=app_config.web_port,
                clock=self._clock,
                enabled=app_config.web_enabled,
                refresh_min_interval_s=app_config.web_refresh_min_s,
                utc_offset_hours=app_config.utc_offset_hours,
                logger=self._log,
            )
        self._dashboard = dashboard

    @property
    def interval_s(self):
        """Seconds between reading cycles."""
        return self._interval_s

    # -- lifecycle ------------------------------------------------------
    def setup(self):
        """Connect, synchronize time, initialize sensors, start the dashboard.

        Never raises for expected hardware/network problems: sensor
        initialization failures are recorded per sensor by the sensor
        manager, Wi-Fi/NTP failures are logged and retried later, and a
        dashboard that cannot bind is logged and simply left disabled.
        """
        self._log("%s starting (device %s)"
                  % (version.__version__, self.config.device_id))
        self._maintain_connections(self._clock())
        results = self._manager.initialize_all()
        for name, status in results.items():
            if status != STATUS_OK:
                self._log("sensor %s unavailable: %s" % (name, status))
        self._dashboard.start()
        return results

    def run(self):
        """Run the periodic reading loop until interrupted (Ctrl-C)."""
        try:
            self.setup()
            self._log("reading every %d s; press Ctrl-C to stop"
                      % self._interval_s)
            while True:
                self.run_once()
                self._wait(self._interval_s)
        except KeyboardInterrupt:
            self._dashboard.stop()
            self._log("stopped")
        return 0

    def run_once(self):
        """Maintain connections, read every sensor, and report each result."""
        self._maintain_connections(self._clock())
        records = self._manager.read_all()
        self._dashboard.update(records)
        for record in records:
            self._report(record)
        return records

    # -- connection maintenance -----------------------------------------
    def _maintain_connections(self, now):
        """Reconnect Wi-Fi / re-synchronize NTP when due, never in a loop."""
        if not self._wifi.is_connected():
            if (self._next_wifi_retry is not None
                    and now < self._next_wifi_retry):
                return
            self._next_wifi_retry = now + self._wifi_retry_interval_s
            if self._wifi.connect():
                self._log("Wi-Fi connected: %s"
                          % (self._wifi.ip_address() or "no IP address"))
            else:
                self._log("Wi-Fi unavailable: %s"
                          % (self._wifi.status().get("last_error")
                             or "unknown reason"))
                return
        self._maybe_sync_time(now)

    def _maybe_sync_time(self, now):
        if (self._next_ntp_attempt is not None
                and now < self._next_ntp_attempt):
            return
        if self._time.sync_ntp(host=self.config.ntp_host,
                               timeout_s=self.config.ntp_timeout_s):
            self._next_ntp_attempt = now + self.config.ntp_interval_s
            self._log("time synchronized (UTC %s)" % self._time.now())
        else:
            self._next_ntp_attempt = now + self._ntp_retry_interval_s
            self._log("NTP time unavailable: %s"
                      % (self._time.last_error or "unknown reason"))

    # -- reporting ------------------------------------------------------
    def _report(self, record):
        stamp = format_timestamp(record.get("timestamp"),
                                 offset_hours=self.config.utc_offset_hours)
        stamp = stamp or TIME_NOT_SET
        name = record.get("sensor")
        status = record.get("status")
        value = record.get("value")
        if (name == WEATHER_SENSOR_NAME and status == STATUS_OK
                and isinstance(value, dict)):
            self._log("%s | %s" % (stamp, format_reading(value)))
        elif status == STATUS_OK:
            self._log("%s | %s: %s" % (stamp, name, value))
        else:
            self._log("%s | %s unavailable: %s"
                      % (stamp, name, record.get("error", status)))

    def _wait(self, seconds):
        """Wait *seconds*, serving dashboard requests while the dashboard is up.

        When the dashboard is disabled or failed to start, this is exactly the
        previous plain ``sleep``. Otherwise requests are served during the wait
        and the reading schedule is anchored to the *last actual reading*: a
        client's refresh request is queued here (never handled inside the HTTP
        handler), the app takes one reading through the normal path, and the
        interval restarts from that reading.
        """
        if not self._dashboard.enabled:
            self._sleep(seconds)
            return
        deadline = self._clock() + seconds
        while True:
            if self._dashboard.service_until(deadline):
                self.run_once()
                deadline = self._clock() + seconds
                continue
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            # The dashboard stopped serving before the deadline (for example a
            # socket error); fall back to sleeping so the schedule is kept.
            self._sleep(remaining)
            return

    def _log(self, message):
        print("[clock-gps] " + message)


def main():
    """Load configuration, build the application, and run it.

    Returns the loop result, or ``None`` when configuration or credentials
    are missing or invalid (a secret-free message is printed instead).
    """
    try:
        app_config = config.load()
    except config.ConfigurationError as exc:
        print("[clock-gps] configuration error:", exc)
        return None
    return ClockGpsApp(app_config).run()


if __name__ == "__main__":
    main()
