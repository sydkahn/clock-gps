"""Weather sensor: turns BME280 readings into documented, normalized data.

Wraps the BME280 driver (``sensors/bme280.py``) and produces a single reading
dict for the sensor manager:

- ``temperature_f`` / ``temperature_c``
- ``humidity_pct``
- ``pressure_station_hpa`` / ``pressure_station_inhg`` -- actual pressure at
  the device
- ``pressure_sea_level_hpa`` / ``pressure_sea_level_inhg`` -- ESTIMATE only
- ``pressure_trend`` -- one of ``rising`` / ``falling`` / ``steady`` /
  ``waiting_for_history``
- ``pressure_trend_delta_hpa`` -- the change over the trend window, or None
- ``elevation_ft`` and ``sea_level_estimated`` (always True)

Station pressure and estimated sea-level pressure are reported under separate
keys and are never substituted for one another.

Sea-level pressure is an ESTIMATE derived from station pressure, station
temperature, and the configured ground elevation. It has NOT been validated
against an independent weather observation and must be treated as approximate.

All conversion, sea-level, and trend logic lives here as pure functions and
small classes so it can be unit-tested on the host without an ESP32. The
hardware driver is created lazily and can be injected for tests.
"""

import json

import config
from sensors.base import STATUS_OK, STATUS_UNAVAILABLE, Sensor, SensorError
from sensors.bme280 import (BME280, DEFAULT_ADDRESS, DEFAULT_SDA_PIN,
                            DEFAULT_SCL_PIN)

# Captured at import so it is available even though ``config`` is later used
# as a constructor parameter name (which shadows the module inside methods).
_DEFAULT_ELEVATION_FT = config.DEFAULT_ELEVATION_FT

# --- Physical constants ---------------------------------------------------
FT_TO_M = 0.3048
PA_PER_HPA = 100.0
PA_PER_INHG = 3386.389
HPA_PER_INHG = 33.86389
STANDARD_LAPSE_RATE = 0.0065  # K/m
SEA_LEVEL_EXPONENT = 5.2559   # g*M/(R*L) for standard constants

# --- Trend classification -------------------------------------------------
TREND_RISING = "rising"
TREND_FALLING = "falling"
TREND_STEADY = "steady"
TREND_WAITING = "waiting_for_history"

DEFAULT_TREND_WINDOW_S = 10800      # approximately three hours
DEFAULT_TREND_THRESHOLD_HPA = 1.0
DEFAULT_TREND_TOLERANCE_S = 1800    # +/- 30 minutes around the window
DEFAULT_HISTORY_MAX_AGE_S = 21600   # keep at most ~6 hours
DEFAULT_HISTORY_MAX_SAMPLES = 16
DEFAULT_PERSIST_INTERVAL_S = 600    # avoid frequent flash writes

HISTORY_FORMAT_VERSION = 1
DEFAULT_HISTORY_PATH = "/clock_gps_pressure.json"

# Plausibility bounds used to reject documented-malformed readings/history.
MIN_PRESSURE_PA = 30000.0    # ~300 hPa
MAX_PRESSURE_PA = 110000.0   # ~1100 hPa
MIN_TEMPERATURE_C = -60.0
MAX_TEMPERATURE_C = 85.0
MIN_HUMIDITY_PCT = 0.0
MAX_HUMIDITY_PCT = 100.0


# --- Pure conversions -----------------------------------------------------
def celsius_to_fahrenheit(celsius):
    """Convert a temperature in degrees Celsius to degrees Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def pa_to_hpa(pascals):
    """Convert pascals to hectopascals (millibars)."""
    return pascals / PA_PER_HPA


def hpa_to_inhg(hpa):
    """Convert hectopascals to inches of mercury."""
    return hpa / HPA_PER_INHG


def pa_to_inhg(pascals):
    """Convert pascals to inches of mercury."""
    return pascals / PA_PER_INHG


def elevation_ft_to_m(feet):
    """Convert an elevation in feet to metres."""
    return feet * FT_TO_M


def sea_level_pressure_hpa(station_hpa, temperature_c, elevation_m):
    """Estimate sea-level pressure (hPa) from a station reading.

    Uses the standard barometric reduction with the station temperature. This
    is an approximation (the official form uses a 12-hour mean temperature)
    and has not been validated against an independent observation.
    """
    if elevation_m == 0:
        return station_hpa
    denominator = temperature_c + STANDARD_LAPSE_RATE * elevation_m + 273.15
    if denominator <= 0:
        raise ValueError("temperature/elevation out of range for sea level")
    factor = 1.0 - (STANDARD_LAPSE_RATE * elevation_m) / denominator
    if factor <= 0:
        raise ValueError("temperature/elevation out of range for sea level")
    return station_hpa * (factor ** (-SEA_LEVEL_EXPONENT))


def classify_trend(delta_hpa, threshold_hpa=DEFAULT_TREND_THRESHOLD_HPA):
    """Classify a pressure change using the configured threshold."""
    if delta_hpa is None:
        return TREND_WAITING
    if delta_hpa >= threshold_hpa:
        return TREND_RISING
    if delta_hpa <= -threshold_hpa:
        return TREND_FALLING
    return TREND_STEADY


def _as_finite_float(value):
    """Return *value* as a finite float, or None when it is not usable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number:  # NaN
        return None
    if number in (float("inf"), float("-inf")):
        return None
    return number


# --- Pressure history and trend ------------------------------------------
class TrendTracker:
    """Keeps a small, monotonic pressure history and derives the trend.

    Samples are ``(unix_timestamp, station_pressure_hpa)`` pairs. History is
    validated on load and never trusted blindly: corrupt, out-of-range,
    duplicate, non-monotonic, stale, and future entries are discarded.
    """

    def __init__(self, window_s=DEFAULT_TREND_WINDOW_S,
                 threshold_hpa=DEFAULT_TREND_THRESHOLD_HPA,
                 tolerance_s=DEFAULT_TREND_TOLERANCE_S,
                 max_age_s=DEFAULT_HISTORY_MAX_AGE_S,
                 max_samples=DEFAULT_HISTORY_MAX_SAMPLES):
        self.window_s = window_s
        self.threshold_hpa = threshold_hpa
        self.tolerance_s = tolerance_s
        self.max_age_s = max_age_s
        self.max_samples = max_samples
        self._samples = []

    def add(self, timestamp, pressure_hpa):
        """Record a sample. Returns True when it was accepted.

        A non-monotonic or duplicate timestamp is ignored rather than
        producing a misleading trend.
        """
        if timestamp is None or pressure_hpa is None:
            return False
        timestamp = int(timestamp)
        value = float(pressure_hpa)
        if value != value:
            return False
        if self._samples and timestamp <= self._samples[-1][0]:
            return False
        self._samples.append((timestamp, value))
        self._prune(timestamp)
        return True

    def _prune(self, now):
        cutoff = now - self.max_age_s
        self._samples = [s for s in self._samples if s[0] >= cutoff]
        if len(self._samples) > self.max_samples:
            self._samples = self._samples[-self.max_samples:]

    def load(self, records):
        """Replace history from stored records, keeping only valid samples."""
        cleaned = []
        for item in records or []:
            try:
                timestamp = int(item[0])
                value = _as_finite_float(item[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            if value is None or not (MIN_PRESSURE_PA / PA_PER_HPA
                                     <= value <= MAX_PRESSURE_PA / PA_PER_HPA):
                continue
            cleaned.append((timestamp, value))
        cleaned.sort(key=lambda sample: sample[0])
        deduped = []
        for timestamp, value in cleaned:
            if deduped and timestamp <= deduped[-1][0]:
                continue
            deduped.append((timestamp, value))
        if len(deduped) > self.max_samples:
            deduped = deduped[-self.max_samples:]
        self._samples = deduped
        return len(deduped)

    def samples(self):
        """Return a copy of the stored samples."""
        return list(self._samples)

    def trend(self, now):
        """Return ``(direction, delta_hpa)`` for the configured window.

        Returns ``(TREND_WAITING, None)`` when there is insufficient valid
        history or the clock is unavailable or has jumped.
        """
        if now is None or len(self._samples) < 2:
            return TREND_WAITING, None
        now = int(now)
        current_ts, current_value = self._samples[-1]
        if abs(now - current_ts) > self.tolerance_s:
            return TREND_WAITING, None  # newest sample stale, or clock jump
        best = None
        best_diff = None
        for timestamp, value in self._samples[:-1]:
            difference = abs((current_ts - timestamp) - self.window_s)
            if difference > self.tolerance_s:
                continue
            if best_diff is None or difference < best_diff:
                best = value
                best_diff = difference
        if best is None:
            return TREND_WAITING, None
        delta = current_value - best
        return classify_trend(delta, self.threshold_hpa), delta


# --- Persistence ----------------------------------------------------------
class PressureHistoryStore:
    """Persist a small pressure history as versioned JSON.

    JSON is used because it is available in MicroPython. Loading is
    defensive: any missing, unreadable, truncated, or unexpected content
    yields an empty history rather than raising.
    """

    def __init__(self, path=DEFAULT_HISTORY_PATH):
        self.path = path

    def load(self):
        try:
            with open(self.path, "r") as handle:
                payload = handle.read()
        except OSError:
            return []
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, dict) or data.get("v") != HISTORY_FORMAT_VERSION:
            return []
        records = data.get("samples")
        if not isinstance(records, list):
            return []
        return records

    def save(self, samples):
        """Write samples atomically enough for a small file; returns success."""
        data = {
            "v": HISTORY_FORMAT_VERSION,
            "samples": [[int(ts), float(value)] for ts, value in samples],
        }
        try:
            with open(self.path, "w") as handle:
                handle.write(json.dumps(data))
        except (OSError, TypeError, ValueError):
            return False
        return True


# --- Sensor ---------------------------------------------------------------
class WeatherSensor(Sensor):
    """BME280-backed weather sensor for the shared sensor manager."""

    name = "weather"

    def __init__(self, config=None, driver=None, time_service=None,
                 name="weather", address=None, sda_pin=None, scl_pin=None,
                 store=None, persist_interval_s=DEFAULT_PERSIST_INTERVAL_S,
                 tracker=None):
        self.name = name
        self._config = config
        self._driver = driver
        self._time = time_service
        self._address = address
        self._sda_pin = sda_pin
        self._scl_pin = scl_pin
        self._store = store
        self._persist_interval_s = persist_interval_s
        self._last_persist_ts = None
        self._initialized = False

        self._elevation_ft = getattr(config, "elevation_ft",
                                     _DEFAULT_ELEVATION_FT)
        window_s = getattr(config, "pressure_trend_window_s",
                           DEFAULT_TREND_WINDOW_S)
        threshold_hpa = getattr(config, "pressure_trend_threshold_hpa",
                                DEFAULT_TREND_THRESHOLD_HPA)
        self._tracker = tracker if tracker is not None else TrendTracker(
            window_s=window_s, threshold_hpa=threshold_hpa)

    # -- Sensor interface ----------------------------------------------
    def initialize(self):
        """Create (if needed) and initialize the driver; load stored history."""
        if self._driver is None:
            self._driver = BME280(
                address=(DEFAULT_ADDRESS if self._address is None
                         else self._address),
                sda_pin=(DEFAULT_SDA_PIN if self._sda_pin is None
                         else self._sda_pin),
                scl_pin=(DEFAULT_SCL_PIN if self._scl_pin is None
                         else self._scl_pin),
            )
        self._driver.initialize()
        if self._store is not None:
            self._tracker.load(self._store.load())
        self._initialized = True
        return True

    def read(self):
        """Return a normalized weather reading dict, or raise SensorError."""
        if not self._initialized or self._driver is None:
            raise SensorError("weather sensor not initialized")
        reading = self._normalize(self._driver.read())

        now = self._now()
        if now is not None:
            if self._tracker.add(now, reading["pressure_station_hpa"]):
                self._maybe_persist(now)
            direction, delta = self._tracker.trend(now)
        else:
            # Valid time is required to compare readings three hours apart.
            direction, delta = TREND_WAITING, None

        reading["pressure_trend"] = direction
        reading["pressure_trend_delta_hpa"] = (
            None if delta is None else round(delta, 2))
        return reading

    def status(self):
        return STATUS_OK if self._initialized else STATUS_UNAVAILABLE

    # -- helpers --------------------------------------------------------
    @property
    def elevation_ft(self):
        return self._elevation_ft

    @property
    def history(self):
        return self._tracker.samples()

    def _now(self):
        if self._time is None:
            return None
        try:
            if not self._time.is_valid():
                return None
            return self._time.now()
        except Exception:  # noqa: BLE001 - a bad time source must not crash
            return None

    def _normalize(self, raw):
        try:
            temperature_c = _as_finite_float(raw["temperature_c"])
            pressure_pa = _as_finite_float(raw["pressure_pa"])
            humidity = _as_finite_float(raw["humidity_pct"])
        except (TypeError, KeyError, IndexError):
            raise SensorError("malformed sensor reading")

        if temperature_c is None or not (MIN_TEMPERATURE_C <= temperature_c
                                         <= MAX_TEMPERATURE_C):
            raise SensorError("malformed temperature reading")
        if pressure_pa is None or not (MIN_PRESSURE_PA <= pressure_pa
                                       <= MAX_PRESSURE_PA):
            raise SensorError("malformed pressure reading")
        if humidity is None or not (MIN_HUMIDITY_PCT <= humidity
                                    <= MAX_HUMIDITY_PCT):
            raise SensorError("malformed humidity reading")

        pressure_hpa = pa_to_hpa(pressure_pa)
        elevation_m = elevation_ft_to_m(self._elevation_ft)
        try:
            sea_level_hpa = sea_level_pressure_hpa(
                pressure_hpa, temperature_c, elevation_m)
        except ValueError:
            raise SensorError("could not estimate sea-level pressure")

        return {
            "temperature_f": round(celsius_to_fahrenheit(temperature_c), 1),
            "temperature_c": round(temperature_c, 2),
            "humidity_pct": round(humidity, 1),
            "pressure_station_hpa": round(pressure_hpa, 2),
            "pressure_station_inhg": round(pa_to_inhg(pressure_pa), 3),
            "pressure_sea_level_hpa": round(sea_level_hpa, 2),
            "pressure_sea_level_inhg": round(hpa_to_inhg(sea_level_hpa), 3),
            "elevation_ft": self._elevation_ft,
            "sea_level_estimated": True,
        }

    def _maybe_persist(self, now):
        if self._store is None:
            return
        if (self._last_persist_ts is not None
                and (now - self._last_persist_ts) < self._persist_interval_s):
            return
        if self._store.save(self._tracker.samples()):
            self._last_persist_ts = now
