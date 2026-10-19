"""Clock GPS device configuration and validation.

This module intentionally avoids MicroPython-only imports (``machine``,
``network``) so that configuration and validation logic can be imported and
unit-tested on the development computer. Hardware access belongs in the
sensor, network, and power modules, never here.

Secrets are not stored in this file. The real secrets live in
``credentials.py`` (see ``credentials.example.py``), which is excluded from
Git. Error messages produced here must never include secret values.
"""

# A value beginning with "<" is treated as an unfilled placeholder from
# credentials.example.py, and therefore as "not configured".
PLACEHOLDER_PREFIX = "<"

DEFAULT_DEVICE_ID = "clock-gps-01"
DEFAULT_TOPIC_PREFIX = "clock-gps"
DEFAULT_NTP_HOST = "pool.ntp.org"
DEFAULT_NTP_INTERVAL_S = 3600
DEFAULT_NTP_TIMEOUT_S = 10
DEFAULT_TELEMETRY_INTERVAL_S = 300
DEFAULT_MQTT_PORT = 1883
DEFAULT_LOG_LEVEL = "info"

# Read-only web dashboard defaults (Phase 6 presentation interface).
DEFAULT_WEB_ENABLED = True
DEFAULT_WEB_PORT = 80
DEFAULT_WEB_REFRESH_MIN_S = 10

# Local UTC offset (whole or fractional hours) used only to *display* times;
# stored timestamps remain UTC. Fixed offset: it does not follow daylight
# saving, so it must be changed by hand when the local DST rule changes.
DEFAULT_UTC_OFFSET_HOURS = -5  # Eastern Standard Time

# Bounds for the display UTC offset.
MIN_UTC_OFFSET_HOURS = -12
MAX_UTC_OFFSET_HOURS = 14

# Bounds for the dashboard's TCP port.
MIN_WEB_PORT = 1
MAX_WEB_PORT = 65535

# Weather sensor defaults.
DEFAULT_ELEVATION_FT = 627
DEFAULT_PRESSURE_TREND_WINDOW_S = 10800  # approximately three hours
DEFAULT_PRESSURE_TREND_THRESHOLD_HPA = 1.0

# Characters allowed in a device id; the id appears in MQTT topics.
DEVICE_ID_ALLOWED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"

# Guard against accidental busy loops by rejecting very small intervals.
MIN_INTERVAL_S = 5

# Bounds for the weather/sea-level configuration.
MIN_ELEVATION_FT = -1500
MAX_ELEVATION_FT = 30000
MIN_TREND_WINDOW_S = 1800


class ConfigurationError(Exception):
    """Configuration or credentials are missing or invalid.

    The message describes what is wrong and never includes credential
    values.
    """


def is_placeholder(value):
    """Return True when *value* is unset or still an example placeholder."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text == "":
        return True
    return text.startswith(PLACEHOLDER_PREFIX)


def validate_device_id(device_id):
    """Return an error message for an invalid device id, or None if valid."""
    if not isinstance(device_id, str) or device_id.strip() == "":
        return "device_id must be a non-empty string"
    for char in device_id:
        if char not in DEVICE_ID_ALLOWED:
            return "device_id may only contain letters, digits, '-' and '_'"
    return None


def _check_interval(name, value):
    """Return a list of problems for an interval setting."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ["%s must be an integer" % name]
    if number < MIN_INTERVAL_S:
        return ["%s must be at least %d seconds" % (name, MIN_INTERVAL_S)]
    return []


def _check_elevation_ft(value):
    """Return a list of problems for the configured ground elevation."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ["elevation_ft must be a number"]
    if number != number:  # NaN
        return ["elevation_ft must be a number"]
    if not (MIN_ELEVATION_FT <= number <= MAX_ELEVATION_FT):
        return ["elevation_ft must be between %d and %d"
                % (MIN_ELEVATION_FT, MAX_ELEVATION_FT)]
    return []


def _check_positive_number(name, value):
    """Return a list of problems for a value that must be > 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ["%s must be a number" % name]
    if number != number or number <= 0:  # NaN or non-positive
        return ["%s must be greater than zero" % name]
    return []


def _check_trend_window(value):
    """Return a list of problems for the pressure-trend window."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ["pressure_trend_window_s must be an integer"]
    if number < MIN_TREND_WINDOW_S:
        return ["pressure_trend_window_s must be at least %d seconds"
                % MIN_TREND_WINDOW_S]
    return []


def _check_bool(name, value):
    """Return a list of problems for a setting that must be true or false."""
    if not isinstance(value, bool):
        return ["%s must be true or false" % name]
    return []


def _check_web_port(value):
    """Return a list of problems for the dashboard TCP port."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return ["web_port must be an integer"]
    if not (MIN_WEB_PORT <= port <= MAX_WEB_PORT):
        return ["web_port must be between %d and %d"
                % (MIN_WEB_PORT, MAX_WEB_PORT)]
    return []


def _check_utc_offset(value):
    """Return a list of problems for the display UTC offset in hours."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ["utc_offset_hours must be a number"]
    if number != number:  # NaN
        return ["utc_offset_hours must be a number"]
    if not (MIN_UTC_OFFSET_HOURS <= number <= MAX_UTC_OFFSET_HOURS):
        return ["utc_offset_hours must be between %d and %d hours"
                % (MIN_UTC_OFFSET_HOURS, MAX_UTC_OFFSET_HOURS)]
    return []


class Credentials:
    """Credentials loaded from the local, git-ignored secrets module."""

    def __init__(self, wifi_ssid=None, wifi_password=None, mqtt_host=None,
                 mqtt_port=DEFAULT_MQTT_PORT, mqtt_username=None,
                 mqtt_password=None):
        self.wifi_ssid = wifi_ssid
        self.wifi_password = wifi_password
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password

    @classmethod
    def from_module(cls, module):
        """Build a Credentials object from an imported credentials module."""
        return cls(
            wifi_ssid=getattr(module, "WIFI_SSID", None),
            wifi_password=getattr(module, "WIFI_PASSWORD", None),
            mqtt_host=getattr(module, "MQTT_HOST", None),
            mqtt_port=getattr(module, "MQTT_PORT", DEFAULT_MQTT_PORT),
            mqtt_username=getattr(module, "MQTT_USERNAME", None),
            mqtt_password=getattr(module, "MQTT_PASSWORD", None),
        )

    def validate(self):
        """Return a list of problems; the values themselves are never shown."""
        problems = []
        if is_placeholder(self.wifi_ssid):
            problems.append("WIFI_SSID is missing or still a placeholder")
        if is_placeholder(self.wifi_password):
            problems.append("WIFI_PASSWORD is missing or still a placeholder")
        # MQTT is optional until Phase 4, but when a host is set its port
        # must be usable.
        if not is_placeholder(self.mqtt_host):
            try:
                port = int(self.mqtt_port)
            except (TypeError, ValueError):
                problems.append("MQTT_PORT must be an integer")
            else:
                if not 1 <= port <= 65535:
                    problems.append("MQTT_PORT must be between 1 and 65535")
        return problems

    def has_mqtt(self):
        """Return True when an MQTT broker has been configured."""
        if is_placeholder(self.mqtt_host):
            return False
        try:
            int(self.mqtt_port)
        except (TypeError, ValueError):
            return False
        return True


class Config:
    """Application configuration for the Clock GPS device."""

    def __init__(self, device_id=DEFAULT_DEVICE_ID,
                 topic_prefix=DEFAULT_TOPIC_PREFIX,
                 ntp_host=DEFAULT_NTP_HOST,
                 ntp_interval_s=DEFAULT_NTP_INTERVAL_S,
                 ntp_timeout_s=DEFAULT_NTP_TIMEOUT_S,
                 telemetry_interval_s=DEFAULT_TELEMETRY_INTERVAL_S,
                 log_level=DEFAULT_LOG_LEVEL,
                 elevation_ft=DEFAULT_ELEVATION_FT,
                 pressure_trend_window_s=DEFAULT_PRESSURE_TREND_WINDOW_S,
                 pressure_trend_threshold_hpa=DEFAULT_PRESSURE_TREND_THRESHOLD_HPA,
                 web_enabled=DEFAULT_WEB_ENABLED,
                 web_port=DEFAULT_WEB_PORT,
                 web_refresh_min_s=DEFAULT_WEB_REFRESH_MIN_S,
                 utc_offset_hours=DEFAULT_UTC_OFFSET_HOURS):
        self.device_id = device_id
        self.topic_prefix = topic_prefix
        self.ntp_host = ntp_host
        self.ntp_interval_s = ntp_interval_s
        self.ntp_timeout_s = ntp_timeout_s
        self.telemetry_interval_s = telemetry_interval_s
        self.log_level = log_level
        # Weather / sea-level settings (ground elevation in feet).
        self.elevation_ft = elevation_ft
        self.pressure_trend_window_s = pressure_trend_window_s
        self.pressure_trend_threshold_hpa = pressure_trend_threshold_hpa
        # Read-only web dashboard settings.
        self.web_enabled = web_enabled
        self.web_port = web_port
        self.web_refresh_min_s = web_refresh_min_s
        # Display-only local UTC offset; stored timestamps stay UTC.
        self.utc_offset_hours = utc_offset_hours
        # Attached by load(); kept separate from non-secret configuration.
        self.credentials = None

    def validate(self):
        """Return a list of configuration problems (empty when valid)."""
        problems = []
        error = validate_device_id(self.device_id)
        if error:
            problems.append(error)
        if not isinstance(self.topic_prefix, str) or self.topic_prefix.strip() == "":
            problems.append("topic_prefix must be a non-empty string")
        if is_placeholder(self.ntp_host):
            problems.append("ntp_host must be set")
        problems.extend(_check_interval("ntp_interval_s", self.ntp_interval_s))
        problems.extend(_check_interval("ntp_timeout_s", self.ntp_timeout_s))
        problems.extend(_check_interval("telemetry_interval_s", self.telemetry_interval_s))
        problems.extend(_check_elevation_ft(self.elevation_ft))
        problems.extend(_check_trend_window(self.pressure_trend_window_s))
        problems.extend(_check_positive_number("pressure_trend_threshold_hpa",
                                               self.pressure_trend_threshold_hpa))
        problems.extend(_check_bool("web_enabled", self.web_enabled))
        problems.extend(_check_web_port(self.web_port))
        problems.extend(_check_interval("web_refresh_min_s", self.web_refresh_min_s))
        problems.extend(_check_utc_offset(self.utc_offset_hours))
        return problems

    def is_valid(self):
        """Convenience wrapper returning True when there are no problems."""
        return not self.validate()

    def topic(self, leaf):
        """Return the MQTT topic for a documented leaf, e.g. 'telemetry'."""
        return "%s/%s/%s" % (self.topic_prefix, self.device_id, leaf)


def load_credentials(credentials_module=None):
    """Load and validate the local credentials module.

    Raises ConfigurationError when the module is missing or incomplete. The
    raised message never contains secret values.
    """
    module = credentials_module
    if module is None:
        try:
            import credentials as module  # local secrets file, git-ignored
        except ImportError:
            raise ConfigurationError(
                "credentials.py was not found; copy credentials.example.py "
                "to credentials.py and fill in the placeholders"
            )
    credentials = Credentials.from_module(module)
    problems = credentials.validate()
    if problems:
        raise ConfigurationError("invalid credentials: " + "; ".join(problems))
    return credentials


def load(credentials_module=None):
    """Return a validated Config with its credentials attached."""
    credentials = load_credentials(credentials_module)
    app_config = Config()
    problems = app_config.validate()
    if problems:
        raise ConfigurationError("invalid configuration: " + "; ".join(problems))
    app_config.credentials = credentials
    return app_config
