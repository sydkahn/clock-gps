"""Connectivity transport modules (Wi-Fi and MQTT) live in this package.

The package is deliberately *not* named ``network``: on the ESP32 the
MicroPython built-in ``network`` module is non-extensible, so it always shadows
a filesystem package of the same name. Naming this package ``connectivity``
keeps it importable on the device while the Wi-Fi driver still imports the
built-in ``network`` module itself.
"""
