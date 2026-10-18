"""Power, battery, and sleep coordination.

Placeholder for Phase 7. Battery chemistry, capacity, charging/protection
circuitry, and regulation are not yet confirmed, so no power logic is
implemented. Later this coordinates ``machine.lightsleep()`` /
``machine.deepsleep()`` with scheduled readings, telemetry, commands, and
OTA, and must never sleep during a critical update write.
"""

PHASE = 7
