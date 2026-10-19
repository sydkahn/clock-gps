"""Read-only web dashboard for the Clock GPS device.

Serves one small HTML page and a JSON status endpoint directly from the ESP32
using MicroPython's built-in ``socket`` module. This is a presentation
interface only:

- It never reads a sensor itself. The reading loop hands it the latest records
  through :meth:`Dashboard.update`; the request handler only formats them, so
  it can never block on I2C or race the sensor.
- It exposes no credentials and no control beyond a rate-limited "refresh now"
  request.
- Pressure is shown as an estimated sea-level value and as a trend. The
  absolute pressure field is explicitly whitelisted in the JSON payload.

MQTT remains the only home-automation interface; this module does not talk to
Home Assistant, Node-RED, Alexa, or any external service.

The ``socket`` and ``select`` modules are imported lazily, so this module can
be imported and its pure helpers unit-tested on the development computer. The
``Dashboard`` class coordinates the server; the module-level helpers are
network- and hardware-independent.
"""

import json

from clock.time_service import format_timestamp

#: Sensor name used by the weather module; the dashboard reports this record.
WEATHER_SENSOR_NAME = "weather"

#: Address the server binds to. 0.0.0.0 makes it reachable from the local LAN;
#: it is never exposed to the public internet by this code.
BIND_ADDRESS = "0.0.0.0"

#: Standard HTTP port, so the dashboard opens by browsing the device IP.
DEFAULT_PORT = 80

#: Listening backlog. The dashboard serves one request at a time.
LISTEN_BACKLOG = 2

# Bounds that keep a slow or hostile client from stalling the reading loop.
MAX_REQUEST_BYTES = 1024
CLIENT_TIMEOUT_S = 2.0
MAX_ACCEPT_ATTEMPTS = 3

# A forced refresh causes an extra sensor read; rate-limit it so the button
# cannot drive rapid I2C activity.
DEFAULT_REFRESH_MIN_INTERVAL_S = 10

CONTENT_TYPE_HTML = "text/html; charset=utf-8"
CONTENT_TYPE_JSON = "application/json; charset=utf-8"
CONTENT_TYPE_TEXT = "text/plain; charset=utf-8"

STATUS_OK = 200
STATUS_ACCEPTED = 202
STATUS_NO_CONTENT = 204
STATUS_BAD_REQUEST = 400
STATUS_NOT_FOUND = 404
STATUS_METHOD_NOT_ALLOWED = 405

_STATUS_TEXT = {
    200: "OK",
    202: "Accepted",
    204: "No Content",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
}

# Route identifiers returned by resolve_request().
ROUTE_INDEX = "index"
ROUTE_STATUS = "status"
ROUTE_REFRESH = "refresh"
ROUTE_FAVICON = "favicon"
ROUTE_NOT_FOUND = "not_found"
ROUTE_METHOD_NOT_ALLOWED = "method_not_allowed"

# The page is a single self-contained document: no external CSS, fonts, or
# scripts. Temperature and humidity lead, followed by compact estimated
# sea-level pressure and its trend. The browser binds these elements to
# /status.json.
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clock GPS</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;padding:20px;background:#0f172a;color:#e2e8f0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;display:flex;justify-content:center}
main{width:100%;max-width:440px}
h1{font-size:1.05rem;font-weight:600;margin:0;color:#94a3b8}
.sub{font-size:.8rem;color:#64748b;margin:4px 0 16px}
.card{background:#1e293b;border-radius:12px;padding:14px;margin-bottom:12px}
.primary .value{font-size:1.65rem}
.pressure-line{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-top:5px}
.pressure{font-size:1.35rem;font-weight:650}
.trend-text{font-size:.85rem;color:#94a3b8;white-space:nowrap}
.arrow{font-size:1rem;font-weight:700;margin-left:4px}
.word{font-weight:700;letter-spacing:.03em}
.delta{font-size:.75rem;color:#94a3b8;margin-top:5px;min-height:1em}
.rising{color:#f87171}.falling{color:#60a5fa}.steady{color:#4ade80}.waiting{color:#94a3b8}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.label{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8}
.value{font-size:1.3rem;font-weight:700;margin-top:6px}
.row{display:flex;justify-content:space-between;font-size:.9rem;padding:5px 0}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:#64748b;vertical-align:middle}
.ok{background:#4ade80}.bad{background:#f87171}
button{width:100%;padding:12px;font-size:1rem;font-weight:600;border:0;border-radius:10px;background:#3b82f6;color:#fff;cursor:pointer}
button:disabled{opacity:.6}
.foot{font-size:.72rem;color:#64748b;text-align:center;margin-top:12px}
</style>
</head>
<body>
<main>
<h1 id="dev">Clock GPS</h1>
<div class="sub">Last reading: <span id="when">-</span> <span id="age"></span></div>
<div class="grid primary">
<div class="card"><div class="label">Temperature</div><div class="value" id="temp">-</div></div>
<div class="card"><div class="label">Humidity</div><div class="value" id="hum">-</div></div>
</div>
<div class="card">
<div class="label">Sea-level pressure (estimated)</div>
<div class="value pressure" id="pressure">-</div>
<div class="pressure-line">
<span class="trend-text">Pressure trend: <span class="word" id="word">WAITING FOR HISTORY</span><span class="arrow" id="arrow">&#8226;</span></span>
</div>
<div class="delta" id="delta"></div>
</div>
<div class="card">
<div class="row"><span><span class="dot" id="wdot"></span>Wi-Fi</span><span id="wtxt">-</span></div>
<div class="row"><span><span class="dot" id="sdot"></span>Sensor</span><span id="stxt">-</span></div>
</div>
<button id="refresh">Refresh now</button>
<div class="foot" id="ver"></div>
</main>
<script>
var TREND={rising:["↑","RISING","rising"],falling:["↓","FALLING","falling"],steady:["→","STEADY","steady"],"waiting_for_history":["•","WAITING FOR HISTORY","waiting"]};
function txt(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
function ageStr(s){if(s===null||s===undefined)return "never";if(s<60)return s+"s ago";if(s<3600)return Math.floor(s/60)+"m ago";return Math.floor(s/3600)+"h ago";}
function render(d){
var w=d.weather||{};
txt("dev",d.device_id||"Clock GPS");
txt("when",d.last_reading_local||"TIME NOT SET");
txt("age",(d.age_s===null||d.age_s===undefined)?"":"("+ageStr(d.age_s)+")");
txt("pressure",(w.pressure_sea_level_inhg===null||w.pressure_sea_level_inhg===undefined)?"-":w.pressure_sea_level_inhg.toFixed(2)+" inHg");
var t=TREND[w.trend]||TREND.waiting_for_history;
txt("arrow",t[0]);
txt("word",t[1]);
document.getElementById("word").className="word "+t[2];
txt("delta",(w.trend_delta_hpa===null||w.trend_delta_hpa===undefined)?"":"Change over window: "+(w.trend_delta_hpa>0?"+":"")+w.trend_delta_hpa+" hPa");
txt("temp",(w.temperature_f===null||w.temperature_f===undefined)?"-":w.temperature_f.toFixed(1)+" °F");
txt("hum",(w.humidity_pct===null||w.humidity_pct===undefined)?"-":w.humidity_pct.toFixed(1)+" %");
var wf=d.wifi||{},sf=d.sensor||{};
document.getElementById("wdot").className="dot "+(wf.connected?"ok":"bad");
txt("wtxt",wf.connected?(wf.ip||"connected"):"offline");
document.getElementById("sdot").className="dot "+((sf.status==="ok")?"ok":"bad");
txt("stxt",sf.status||"-");
txt("ver","v"+(d.version||"?")+" · "+(d.device_id||""));
}
function load(){fetch("/status.json",{cache:"no-store"}).then(function(r){return r.json();}).then(render).catch(function(){});}
document.getElementById("refresh").addEventListener("click",function(){var b=this;b.disabled=true;fetch("/api/refresh",{method:"POST"}).then(function(){setTimeout(function(){load();b.disabled=false;},1500);}).catch(function(){b.disabled=false;});});
load();setInterval(load,30000);
</script>
</body>
</html>
"""


# --- Pure helpers ---------------------------------------------------------
def render_index_html():
    """Return the dashboard HTML document as a string."""
    return INDEX_HTML


def _latest_weather_record(records):
    for record in records or []:
        if record.get("sensor") == WEATHER_SENSOR_NAME:
            return record
    return None


def _weather_view(value):
    """Return the dashboard's whitelisted view of a weather reading."""
    return {
        "temperature_f": value.get("temperature_f"),
        "humidity_pct": value.get("humidity_pct"),
        "pressure_sea_level_inhg": value.get("pressure_sea_level_inhg"),
        "trend": value.get("pressure_trend"),
        "trend_delta_hpa": value.get("pressure_trend_delta_hpa"),
    }


def build_status_payload(records=None, wifi_status=None, now=None,
                         device_id=None, version=None, utc_offset_hours=0):
    """Build the JSON-ready status dict from the latest sensor records.

    Pure function: it does not read hardware and never raises for missing
    data. ``records`` is the list returned by ``SensorManager.read_all()``.

    ``server_time`` is the current clock, while ``last_reading`` (Unix epoch)
    and ``last_reading_local`` (formatted local time) describe the most recent
    *actual* reading. They are kept distinct so the page never presents the
    current server time as the reading time. ``utc_offset_hours`` only affects
    the displayed local time; the epoch fields stay in UTC.
    """
    record = _latest_weather_record(records)
    if record is None:
        sensor = {"name": WEATHER_SENSOR_NAME, "status": "unknown"}
        weather = None
        last_reading = None
    else:
        sensor = {"name": record.get("sensor"), "status": record.get("status")}
        value = record.get("value")
        weather = _weather_view(value) if isinstance(value, dict) else None
        last_reading = record.get("timestamp")

    age_s = None
    if now is not None and last_reading is not None:
        age_s = max(0, int(now) - int(last_reading))

    wifi = wifi_status or {}
    return {
        "ok": True,
        "device_id": device_id,
        "version": version,
        "server_time": now,
        "last_reading": last_reading,
        "last_reading_local": format_timestamp(last_reading,
                                               offset_hours=utc_offset_hours),
        "age_s": age_s,
        "wifi": {
            "state": wifi.get("state"),
            "connected": bool(wifi.get("connected")),
            "ip": wifi.get("ip"),
        },
        "sensor": sensor,
        "weather": weather,
    }


def parse_request_line(line):
    """Parse an HTTP request line into ``(method, path, query)`` or None.

    Accepts ``bytes`` or ``str``. Only the request line is interpreted;
    headers and any body are ignored.
    """
    if not line:
        return None
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except Exception:  # noqa: BLE001 - malformed bytes are a bad request
            return None
    line = line.strip()
    if not line:
        return None
    parts = line.split(" ")
    if len(parts) != 3:
        return None
    method, target, version = parts
    if not method or not target or not version.startswith("HTTP/"):
        return None
    path, _sep, query = target.partition("?")
    if not path.startswith("/"):
        return None
    return method.upper(), path, query


def resolve_request(method, path):
    """Return the route identifier for a parsed request."""
    if method == "GET" and path == "/":
        return ROUTE_INDEX
    if method == "GET" and path == "/status.json":
        return ROUTE_STATUS
    if method == "POST" and path == "/api/refresh":
        return ROUTE_REFRESH
    if path == "/favicon.ico":
        return ROUTE_FAVICON
    if path in ("/", "/status.json", "/api/refresh"):
        return ROUTE_METHOD_NOT_ALLOWED
    return ROUTE_NOT_FOUND


def format_response(status, content_type=None, body=b""):
    """Return a complete HTTP/1.1 response (headers + body) as bytes.

    Every response closes the connection: the dashboard serves one request per
    connection, which keeps memory use flat and avoids keep-alive state.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    lines = ["HTTP/1.1 %d %s" % (status, _STATUS_TEXT.get(status, ""))]
    if content_type:
        lines.append("Content-Type: %s" % content_type)
    lines.append("Content-Length: %d" % len(body))
    lines.append("Cache-Control: no-store")
    lines.append("Connection: close")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    return head + body


def _default_clock():
    """Return monotonic-ish seconds (MicroPython or host)."""
    import time
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms() / 1000.0
    return time.monotonic()


def _default_log(message):
    print("[clock-gps] " + message)


def _describe_error(exc):
    """Return a secret-free one-line description of *exc*."""
    text = str(exc)
    if text:
        return "%s: %s" % (type(exc).__name__, text)
    return type(exc).__name__


class Dashboard:
    """Single-threaded HTTP dashboard driven from the application loop.

    The reading loop calls :meth:`update` with the latest records and
    :meth:`service_until` in place of a plain sleep. Incoming requests are
    answered from the cached records; the loop is told when a client asked for
    an immediate refresh so it can take the reading itself.
    """

    def __init__(self, device_id=None, version=None, wifi=None,
                 time_service=None, utc_offset_hours=0, port=DEFAULT_PORT,
                 clock=None, socket_module=None, select_module=None,
                 enabled=True,
                 refresh_min_interval_s=DEFAULT_REFRESH_MIN_INTERVAL_S,
                 logger=None):
        self._device_id = device_id
        self._version = version
        self._wifi = wifi
        self._time = time_service
        self._utc_offset_hours = utc_offset_hours
        self._port = int(port)
        self._clock = clock if clock is not None else _default_clock
        self._socket_module = socket_module
        self._select_module = select_module
        self._enabled = bool(enabled)
        self._refresh_min_interval_s = refresh_min_interval_s
        self._logger = logger if logger is not None else _default_log
        self._server = None
        self._poller = None
        self._index_bytes = None
        self._records = None
        self._refresh_requested = False
        self._last_refresh_ts = None

    # -- state -----------------------------------------------------------
    @property
    def enabled(self):
        """True when the server is bound and able to serve requests."""
        return self._enabled and self._server is not None

    @property
    def port(self):
        return self._port

    @property
    def refresh_requested(self):
        """True while a client's refresh request is waiting to be served."""
        return self._refresh_requested

    def take_refresh_request(self):
        """Consume and return the pending refresh request flag."""
        if self._refresh_requested:
            self._refresh_requested = False
            return True
        return False

    def update(self, records):
        """Store the latest sensor records to report (no sensor access)."""
        self._records = records

    def url(self):
        """Return a human-readable URL, using the current IP when known."""
        ip = None
        if self._wifi is not None and self._wifi.is_connected():
            ip = self._wifi.ip_address()
        suffix = "" if self._port == DEFAULT_PORT else ":%d" % self._port
        return "http://%s%s" % (ip or "<device-ip>", suffix)

    # -- lifecycle -------------------------------------------------------
    def _get_socket_module(self):
        if self._socket_module is None:
            import socket
            self._socket_module = socket
        return self._socket_module

    def _get_select_module(self):
        if self._select_module is None:
            import select
            self._select_module = select
        return self._select_module

    def start(self):
        """Bind and listen. Returns True when the server is ready.

        Never raises: a dashboard failure must not stop the application. The
        reason is logged without secrets.
        """
        if not self._enabled:
            self._logger("dashboard disabled")
            return False
        server = None
        try:
            socket = self._get_socket_module()
            select = self._get_select_module()
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((BIND_ADDRESS, self._port))
            server.listen(LISTEN_BACKLOG)
            poller = select.poll()
            poller.register(server, select.POLLIN)
        except Exception as exc:  # noqa: BLE001 - never fatal
            self._logger("dashboard unavailable: %s" % _describe_error(exc))
            if server is not None:
                try:
                    server.close()
                except Exception:  # noqa: BLE001
                    pass
            self._server = None
            self._poller = None
            return False
        self._server = server
        self._poller = poller
        self._logger("dashboard ready: %s" % self.url())
        return True

    def stop(self):
        """Close the listening socket, if open."""
        if self._poller is not None and self._server is not None:
            try:
                self._poller.unregister(self._server)
            except Exception:  # noqa: BLE001
                pass
        if self._server is not None:
            try:
                self._server.close()
            except Exception:  # noqa: BLE001
                pass
        self._server = None
        self._poller = None

    # -- serving ---------------------------------------------------------
    def service_until(self, deadline):
        """Serve requests until *deadline* (monotonic seconds).

        Returns True when a client requested an immediate refresh (the caller
        should take a reading now); False when the deadline was reached. This
        replaces a plain sleep, so the waiting period is still spent serving
        the dashboard without delaying the reading schedule.
        """
        if not self.enabled:
            return False
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            try:
                ready = self._poller.poll(int(remaining * 1000))
            except Exception as exc:  # noqa: BLE001 - never fatal
                self._logger("dashboard poll failed: %s" % _describe_error(exc))
                return False
            if not ready:
                return False
            served = False
            for _attempt in range(MAX_ACCEPT_ATTEMPTS):
                if self._serve_one():
                    served = True
                    break
            if not served:
                return False
            if self.take_refresh_request():
                return True

    def _serve_one(self):
        """Accept and handle at most one connection. Returns True on success."""
        try:
            conn, _addr = self._server.accept()
        except Exception as exc:  # noqa: BLE001 - transient; caller re-checks
            self._logger("dashboard accept failed: %s" % _describe_error(exc))
            return False
        try:
            conn.settimeout(CLIENT_TIMEOUT_S)
            self._handle(conn)
        except Exception as exc:  # noqa: BLE001 - one client must not crash us
            self._logger("dashboard request failed: %s" % _describe_error(exc))
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        return True

    def _read_request(self, conn):
        """Read the request header block, bounded by MAX_REQUEST_BYTES.

        The whole header block is consumed, not just the request line. Closing
        a connection with unread request bytes makes the stack send a TCP RST
        instead of a clean FIN, and a browser can treat that as a failed page
        load -- a blank dashboard. Returns the request line bytes.
        """
        data = b""
        while len(data) < MAX_REQUEST_BYTES:
            try:
                chunk = conn.recv(256)
            except Exception:  # noqa: BLE001 - timeout or reset
                break
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data or b"\n\n" in data:
                break
        end = data.find(b"\n")
        return data if end < 0 else data[:end]

    def _handle(self, conn):
        request = parse_request_line(self._read_request(conn))
        if request is None:
            self._send(conn, format_response(STATUS_BAD_REQUEST,
                                             CONTENT_TYPE_TEXT,
                                             b"bad request\n"))
            return
        method, path, _query = request
        route = resolve_request(method, path)
        if route == ROUTE_INDEX:
            self._send(conn, format_response(STATUS_OK, CONTENT_TYPE_HTML,
                                             self._index_body()))
        elif route == ROUTE_STATUS:
            self._send(conn, self._json_response(STATUS_OK))
        elif route == ROUTE_REFRESH:
            accepted = self._request_refresh()
            self._send(conn, self._json_response(
                STATUS_ACCEPTED if accepted else STATUS_OK))
        elif route == ROUTE_FAVICON:
            self._send(conn, format_response(STATUS_NO_CONTENT))
        elif route == ROUTE_METHOD_NOT_ALLOWED:
            self._send(conn, format_response(STATUS_METHOD_NOT_ALLOWED,
                                             CONTENT_TYPE_TEXT,
                                             b"method not allowed\n"))
        else:
            self._send(conn, format_response(STATUS_NOT_FOUND,
                                             CONTENT_TYPE_TEXT,
                                             b"not found\n"))

    def _send(self, conn, data):
        """Write all of *data* to *conn*, tolerating short writes.

        MicroPython's ``socket.write`` can return after a partial send when the
        send buffer is full, so the remainder is written in a loop rather than
        assuming one call sends everything.
        """
        sendall = getattr(conn, "sendall", None)
        if sendall is not None:
            sendall(data)
            return
        remaining = data
        while remaining:
            written = conn.write(remaining)
            if not written:
                raise OSError("socket write made no progress")
            remaining = remaining[written:]

    def _index_body(self):
        if self._index_bytes is None:
            self._index_bytes = render_index_html().encode("utf-8")
        return self._index_bytes

    def _json_response(self, status):
        payload = build_status_payload(
            records=self._records,
            wifi_status=self._wifi_status(),
            now=self._now(),
            device_id=self._device_id,
            version=self._version,
            utc_offset_hours=self._utc_offset_hours,
        )
        return format_response(status, CONTENT_TYPE_JSON,
                               json.dumps(payload).encode("utf-8"))

    def _request_refresh(self):
        """Rate-limit and record a refresh request. Returns True if accepted."""
        now = self._clock()
        if (self._last_refresh_ts is not None
                and (now - self._last_refresh_ts) < self._refresh_min_interval_s):
            return False
        self._last_refresh_ts = now
        self._refresh_requested = True
        return True

    def _wifi_status(self):
        if self._wifi is None:
            return None
        try:
            return self._wifi.status()
        except Exception:  # noqa: BLE001 - status must never break a request
            return None

    def _now(self):
        if self._time is None:
            return None
        try:
            return self._time.now()
        except Exception:  # noqa: BLE001
            return None
