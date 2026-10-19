"""Timekeeping service shared by the clock, sensors, and telemetry.

This module is hardware-independent at import time: the MicroPython-only
``ntptime`` module is imported lazily, so the module can be imported and
unit-tested on the development computer. The optional ``ntp_module`` and
``time_module`` constructor arguments let tests inject fakes.

Time is stored as whole seconds since the Unix epoch (1970-01-01T00:00:00Z)
in UTC. Conversion to local/display time is a separate concern; the small
:func:`format_timestamp` helper exists only for callers that need a
human-readable local stamp, and returns ``None`` when no time is set.

MicroPython epoch
-----------------
This ESP32 MicroPython build uses 2000-01-01 UTC as its epoch, confirmed on
hardware: ``time.gmtime(0)`` returned ``(2000, 1, 1, 0, 0, 0, 5, 1)``.
Therefore ``time.time()`` returns seconds since 2000, not since 1970. Always
convert with :func:`micropython_to_unix` before storing or publishing a
timestamp; never treat a MicroPython timestamp as a Unix timestamp.

Sources
-------
NTP is the initial source (Phase 3). GPS (Phase 8) will reuse
:meth:`TimeService.set_time`. Other modules must read time through this
interface rather than calling NTP or GPS directly.
"""

# --- Epoch handling -------------------------------------------------------
#
# Unix uses 1970-01-01 UTC. This MicroPython build uses 2000-01-01 UTC. The
# fixed difference (30 years, including 7 leap days) is 946684800 seconds.
MICROPYTHON_EPOCH_YEAR = 2000
UNIX_EPOCH_OFFSET_S = 946684800

# Anything earlier than this is treated as implausible for a synced clock. It
# guards against an NTP call that reports success without actually updating
# the real-time clock.
MIN_PLAUSIBLE_UNIX_S = 1577836800  # 2020-01-01T00:00:00Z

SOURCE_NTP = "ntp"
SOURCE_GPS = "gps"


def micropython_to_unix(micropython_seconds):
    """Convert MicroPython-epoch seconds (2000) to Unix-epoch seconds (1970)."""
    return int(micropython_seconds) + UNIX_EPOCH_OFFSET_S


def unix_to_micropython(unix_seconds):
    """Convert Unix-epoch seconds (1970) to MicroPython-epoch seconds (2000)."""
    return int(unix_seconds) - UNIX_EPOCH_OFFSET_S


def is_plausible(unix_seconds):
    """Return True when *unix_seconds* is a reasonable, synced timestamp."""
    if unix_seconds is None:
        return False
    return int(unix_seconds) >= MIN_PLAUSIBLE_UNIX_S


def _to_hour12(hour):
    """Convert a 0-23 hour to a 1-12 hour for 12-hour display."""
    hour = hour % 12
    return 12 if hour == 0 else hour


def format_timestamp(unix_seconds, offset_hours=0, gmtime=None):
    """Format Unix-epoch seconds as local ``YYYY-MM-DD hh:mm:ss AM/PM``.

    *offset_hours* is the local UTC offset applied for display only; the
    stored Unix timestamp is never changed. Returns ``None`` when
    *unix_seconds* is ``None``, so callers can show their own "not set" text
    instead of inventing a time.

    The calendar is derived with UTC (``time.gmtime``) after shifting by the
    offset, so the result does not depend on the host or device timezone.
    *gmtime* is an optional callable taking Unix-epoch seconds and returning a
    struct_time-like 8-tuple; it exists so tests can inject a fixed instant.
    """
    if unix_seconds is None:
        return None
    shifted = int(unix_seconds) + int(offset_hours * 3600)
    if gmtime is None:
        import time
        if hasattr(time, "ticks_ms"):  # MicroPython: epoch is 2000-01-01
            stamp = time.gmtime(unix_to_micropython(shifted))
        else:
            stamp = time.gmtime(shifted)
    else:
        stamp = gmtime(shifted)
    return "%04d-%02d-%02d %02d:%02d:%02d %s" % (
        stamp[0], stamp[1], stamp[2], _to_hour12(stamp[3]), stamp[4],
        stamp[5], "AM" if stamp[3] < 12 else "PM")


def _describe_error(exc):
    """Return a secret-free one-line description of *exc*."""
    text = str(exc)
    if text:
        return "%s: %s" % (type(exc).__name__, text)
    return type(exc).__name__


class TimeService:
    """Tracks time validity, its source, and synchronization status."""

    def __init__(self, ntp_module=None, time_module=None):
        self._epoch = None
        self._source = None
        self._last_sync_epoch = None
        self._last_sync_ok = None
        self._last_error = None
        self._sync_count = 0
        self._ntp_module = ntp_module
        self._time_module = time_module

    # -- lazy hardware imports -----------------------------------------
    def _get_time_module(self):
        if self._time_module is None:
            import time
            self._time_module = time
        return self._time_module

    def _get_ntp_module(self):
        if self._ntp_module is None:
            import ntptime
            self._ntp_module = ntptime
        return self._ntp_module

    # -- recording ------------------------------------------------------
    def set_time(self, epoch_seconds, source):
        """Record Unix-epoch seconds (UTC) from *source*.

        Raises ValueError if no timestamp is supplied. Time is not treated as
        valid merely because a source reported something; callers remain
        responsible for validating the source reading first. For NTP, prefer
        :meth:`sync_ntp`, which applies plausibility checks.
        """
        if epoch_seconds is None:
            raise ValueError("epoch_seconds must not be None")
        self._epoch = int(epoch_seconds)
        self._source = source
        self._last_sync_epoch = self._epoch
        self._last_sync_ok = True
        self._last_error = None
        self._sync_count += 1

    def set_micropython_time(self, micropython_seconds, source=SOURCE_NTP):
        """Record a MicroPython-epoch timestamp, converting it to Unix."""
        self.set_time(micropython_to_unix(micropython_seconds), source)

    def mark_invalid(self):
        """Forget the current time and source, e.g. after an explicit reset."""
        self._epoch = None
        self._source = None

    # -- NTP ------------------------------------------------------------
    def sync_ntp(self, host=None, timeout_s=None):
        """Synchronize using NTP. Returns True on success, False otherwise.

        Never raises for expected network/NTP failures. On failure the clock
        is not marked synchronized and a secret-free reason is stored. A
        previously valid time is preserved; the failure is reported through
        the last-attempt status instead.
        """
        try:
            ntp = self._get_ntp_module()
            time_module = self._get_time_module()
            if host is not None:
                ntp.host = host
            if timeout_s is not None:
                ntp.timeout = int(timeout_s)
            ntp.settime()
            unix_seconds = micropython_to_unix(time_module.time())
        except Exception as exc:  # noqa: BLE001 - network/NTP failures
            self._last_sync_ok = False
            self._last_error = _describe_error(exc)
            return False

        if not is_plausible(unix_seconds):
            self._last_sync_ok = False
            self._last_error = ("NTP reported success but the clock was not "
                                "updated to a plausible time")
            return False

        self.set_time(unix_seconds, SOURCE_NTP)
        return True

    # -- accessors ------------------------------------------------------
    def is_valid(self):
        """Return True when a valid timestamp is currently held."""
        return self._epoch is not None

    def now(self):
        """Return UTC seconds since the Unix epoch, or None when invalid."""
        return self._epoch

    def status(self):
        """Return a secret-free status snapshot for logs and telemetry."""
        return {
            "synced": self._epoch is not None,
            "source": self._source,
            "last_sync_epoch": self._last_sync_epoch,
            "last_sync_ok": self._last_sync_ok,
            "last_error": self._last_error,
            "sync_count": self._sync_count,
        }

    @property
    def source(self):
        """Name of the source that last set time, or None."""
        return self._source

    @property
    def last_sync_epoch(self):
        """Unix timestamp of the last successful sync, or None."""
        return self._last_sync_epoch

    @property
    def last_error(self):
        """Secret-free reason for the most recent failed sync, or None."""
        return self._last_error

    @property
    def synced(self):
        """True when a valid timestamp is currently held."""
        return self._epoch is not None

    @property
    def sync_count(self):
        """Number of successful time records so far."""
        return self._sync_count
