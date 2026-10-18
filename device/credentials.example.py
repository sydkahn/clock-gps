"""Example credentials file -- placeholders only.

Copy this file to ``credentials.py`` in the same directory and replace the
placeholders with real values. The real ``credentials.py`` is excluded from
Git by ``.gitignore`` and must never be committed.

Do not put real passwords, tokens, Wi-Fi credentials, or private keys in
this file. Values that start with "<" are treated as "not configured" by
``config.py``.

The MQTT broker details are for the Proxmox server and are not yet decided;
leave them as placeholders until the broker address, port, and
authentication are confirmed.
"""

# Wi-Fi network used by the device (required).
WIFI_SSID = "<your-wifi-ssid>"
WIFI_PASSWORD = "<your-wifi-password>"

# MQTT broker on the Proxmox server (optional until Phase 4).
MQTT_HOST = "<broker-host-or-ip>"
MQTT_PORT = 1883
MQTT_USERNAME = "<mqtt-username>"
MQTT_PASSWORD = "<mqtt-password>"
