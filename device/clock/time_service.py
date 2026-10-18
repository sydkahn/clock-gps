"""Timekeeping service shared by the clock, sensors, and telemetry.

This module is hardware-independent and has no MicroPython-only imports, so
it can be unit-tested on the development computer.

Time is stored as whole seconds since the Unix epoch in UTC. Conversion to
local/display time is a separate concern and is not done here. Later phases
add NTP (Phase 3) and GPS (Phase 8) as sources; those sources call
:meth:`TimeService.set_time` and are selected by the caller. Other modules
must read time through this interface rather than calling NTP or GPS
directly.
"""


class TimeService:
    """Tracks whether time is valid and which source last set it."""

    def __init__(self):
        self._epoch = None
        self._source = None

    def set_time(self, epoch_seconds, source):
        """Record time from *source* (for example ``"ntp"`` or ``"gps"``).

        Raises ValueError if no timestamp is supplied. Time is not treated
        as valid merely because a source reported something; callers remain
        responsible for validating the source reading first.
        """
        if epoch_seconds is None:
            raise ValueError("epoch_seconds must not be None")
        self._epoch = int(epoch_seconds)
        self._source = source

    def mark_invalid(self):
        """Forget the current time and source, e.g. after a failed sync."""
        self._epoch = None
        self._source = None

    def is_valid(self):
        """Return True when a timestamp has been recorded."""
        return self._epoch is not None

    def now(self):
        """Return UTC seconds since the Unix epoch, or None when invalid."""
        return self._epoch

    @property
    def source(self):
        """Return the name of the source that last set time, or None."""
        return self._source
