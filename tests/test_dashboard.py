"""Host-side tests for ``device/connectivity/dashboard.py``.

No hardware and no real sockets are used. The pure helpers are exercised
directly, and the request handler is driven with in-memory fake connections
plus a fake poller/listening socket so the serving loop can be tested without a
network.
"""

import json
import unittest

import _support  # noqa: F401  (adjusts sys.path)
from connectivity import dashboard
from sensors.base import STATUS_ERROR, STATUS_OK

NOW = 1700000100


def weather_value(temperature_f=68.0, humidity_pct=50.0, trend="rising",
                   delta_hpa=2.5):
    """A weather reading with every field the real sensor produces."""
    return {
        "temperature_f": temperature_f,
        "temperature_c": 20.0,
        "humidity_pct": humidity_pct,
        "pressure_station_hpa": 990.0,
        "pressure_station_inhg": 29.235,
        "pressure_sea_level_hpa": 1012.26,
        "pressure_sea_level_inhg": 29.892,
        "elevation_ft": 627,
        "sea_level_estimated": True,
        "pressure_trend": trend,
        "pressure_trend_delta_hpa": delta_hpa,
    }


def weather_record(trend="rising", delta_hpa=2.5, timestamp=NOW - 10,
                   status=STATUS_OK, value=True):
    return {
        "sensor": dashboard.WEATHER_SENSOR_NAME,
        "status": status,
        "value": weather_value(trend=trend, delta_hpa=delta_hpa) if value else None,
        "timestamp": timestamp,
    }


class FakeWifi:
    def __init__(self, connected=True, ip="10.0.0.203", state="connected"):
        self._connected = connected
        self._ip = ip
        self._state = state

    def is_connected(self):
        return self._connected

    def ip_address(self):
        return self._ip if self._connected else None

    def status(self):
        return {
            "state": self._state,
            "connected": self._connected,
            "ip": self._ip if self._connected else None,
            "credentials_configured": True,
            "last_error": None,
        }


class FakeTime:
    def __init__(self, now=NOW):
        self._now = now

    def now(self):
        return self._now


class FakeClock:
    """Monotonic callable clock used to drive the serving loop."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeConn:
    def __init__(self, request=b"GET / HTTP/1.1\r\nHost: clock-gps\r\n\r\n"):
        self._in = request
        self.written = b""
        self.closed = False
        self.timeout = None

    def recv(self, size):
        chunk, self._in = self._in[:size], self._in[size:]
        return chunk

    def write(self, data):
        self.written += data
        return len(data)

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class FakePoller:
    """Replays a scripted list of poll() results."""

    def __init__(self, events):
        self._events = list(events)
        self.timeouts = []
        self.registered = None
        self.unregistered = []

    def register(self, obj, event):
        self.registered = (obj, event)

    def unregister(self, obj):
        self.unregistered.append(obj)

    def poll(self, timeout_ms):
        self.timeouts.append(timeout_ms)
        if self._events:
            return self._events.pop(0)
        return []


class FakeServer:
    def __init__(self, connections):
        self._connections = list(connections)
        self.closed = False
        self.accepted = 0

    def accept(self):
        if not self._connections:
            raise OSError("no pending connection")
        self.accepted += 1
        return self._connections.pop(0), ("127.0.0.1", 12345)

    def close(self):
        self.closed = True


def make_dashboard(**kwargs):
    kwargs.setdefault("wifi", FakeWifi())
    kwargs.setdefault("time_service", FakeTime())
    kwargs.setdefault("device_id", "clock-gps-01")
    kwargs.setdefault("version", "0.5.0")
    kwargs.setdefault("utc_offset_hours", 0)
    kwargs.setdefault("logger", lambda message: None)
    return dashboard.Dashboard(**kwargs)


def response_parts(raw):
    head, _sep, body = raw.partition(b"\r\n\r\n")
    return head, body


class PayloadTests(unittest.TestCase):
    def test_reports_trend_temperature_and_humidity(self):
        payload = dashboard.build_status_payload(
            records=[weather_record()],
            wifi_status=FakeWifi().status(),
            now=NOW,
            device_id="clock-gps-01",
            version="0.5.0",
        )
        self.assertTrue(payload["ok"])
        self.assertEqual("clock-gps-01", payload["device_id"])
        self.assertEqual(10, payload["age_s"])
        self.assertEqual(NOW - 10, payload["last_reading"])
        self.assertEqual(68.0, payload["weather"]["temperature_f"])
        self.assertEqual(50.0, payload["weather"]["humidity_pct"])
        self.assertEqual("rising", payload["weather"]["trend"])
        self.assertEqual(2.5, payload["weather"]["trend_delta_hpa"])
        self.assertTrue(payload["wifi"]["connected"])
        self.assertEqual("10.0.0.203", payload["wifi"]["ip"])
        self.assertEqual(STATUS_OK, payload["sensor"]["status"])

    def test_weather_fields_are_whitelisted(self):
        payload = dashboard.build_status_payload(
            records=[weather_record()], wifi_status=FakeWifi().status(),
            now=NOW, device_id="d", version="v")
        self.assertEqual(
            {"temperature_f", "humidity_pct", "trend", "trend_delta_hpa"},
            set(payload["weather"].keys()))
        # The strongest guarantee: no absolute pressure reaches the payload.
        self.assertNotIn("pressure", json.dumps(payload))

    def test_handles_missing_sensor(self):
        payload = dashboard.build_status_payload(
            records=[], wifi_status=None, now=NOW, device_id="d", version="v")
        self.assertIsNone(payload["weather"])
        self.assertIsNone(payload["last_reading"])
        self.assertIsNone(payload["age_s"])
        self.assertEqual("unknown", payload["sensor"]["status"])
        self.assertFalse(payload["wifi"]["connected"])
        self.assertIsNone(payload["wifi"]["ip"])

    def test_handles_sensor_error_record(self):
        record = weather_record(value=False, status=STATUS_ERROR)
        record["error"] = "boom"
        payload = dashboard.build_status_payload(
            records=[record], wifi_status=FakeWifi().status(), now=NOW,
            device_id="d", version="v")
        self.assertEqual(STATUS_ERROR, payload["sensor"]["status"])
        self.assertIsNone(payload["weather"])

    def test_age_never_negative(self):
        record = weather_record(timestamp=NOW + 5)
        payload = dashboard.build_status_payload(
            records=[record], now=NOW)
        self.assertEqual(0, payload["age_s"])

    def test_reading_timestamp_is_distinct_from_server_time(self):
        payload = dashboard.build_status_payload(
            records=[weather_record(timestamp=1700000000)], wifi_status=None,
            now=1700000100, device_id="d", version="v", utc_offset_hours=-5)
        self.assertEqual(1700000000, payload["last_reading"])
        self.assertEqual("2023-11-14 05:13:20 PM", payload["last_reading_local"])
        self.assertEqual(1700000100, payload["server_time"])
        self.assertEqual(100, payload["age_s"])

    def test_local_time_honours_the_configured_offset(self):
        utc = dashboard.build_status_payload(
            records=[weather_record(timestamp=1700000000)],
            now=1700000000, device_id="d", version="v", utc_offset_hours=0)
        eastern = dashboard.build_status_payload(
            records=[weather_record(timestamp=1700000000)],
            now=1700000000, device_id="d", version="v", utc_offset_hours=-5)
        self.assertEqual("2023-11-14 10:13:20 PM", utc["last_reading_local"])
        self.assertEqual("2023-11-14 05:13:20 PM",
                         eastern["last_reading_local"])
        # The machine-readable epoch is not affected by the display offset.
        self.assertEqual(utc["last_reading"], eastern["last_reading"])

    def test_missing_reading_has_no_timestamp(self):
        payload = dashboard.build_status_payload(
            records=[], now=2000, device_id="d", version="v")
        self.assertIsNone(payload["last_reading"])
        self.assertIsNone(payload["last_reading_local"])


class RequestParsingTests(unittest.TestCase):
    def test_parses_simple_request(self):
        self.assertEqual(("GET", "/", ""),
                         dashboard.parse_request_line(b"GET / HTTP/1.1"))

    def test_parses_query_string(self):
        self.assertEqual(
            ("GET", "/status.json", "x=1"),
            dashboard.parse_request_line("GET /status.json?x=1 HTTP/1.1"))

    def test_strips_trailing_carriage_return(self):
        self.assertEqual(
            ("POST", "/api/refresh", ""),
            dashboard.parse_request_line(b"POST /api/refresh HTTP/1.1\r"))

    def test_lowercase_method_is_upper_cased(self):
        self.assertEqual(("GET", "/", ""),
                         dashboard.parse_request_line(b"get / HTTP/1.1"))

    def test_rejects_malformed_lines(self):
        for raw in (b"", b"   ", b"GET", b"GET /", b"GET / NOTHTTP",
                    b"GET http://host/ HTTP/1.1", b"GET / HTTP/1.1 extra"):
            self.assertIsNone(dashboard.parse_request_line(raw), raw)


class RouteTests(unittest.TestCase):
    def test_recognized_routes(self):
        self.assertEqual(dashboard.ROUTE_INDEX,
                         dashboard.resolve_request("GET", "/"))
        self.assertEqual(dashboard.ROUTE_STATUS,
                         dashboard.resolve_request("GET", "/status.json"))
        self.assertEqual(dashboard.ROUTE_REFRESH,
                         dashboard.resolve_request("POST", "/api/refresh"))
        self.assertEqual(dashboard.ROUTE_FAVICON,
                         dashboard.resolve_request("GET", "/favicon.ico"))

    def test_unknown_path_is_not_found(self):
        self.assertEqual(dashboard.ROUTE_NOT_FOUND,
                         dashboard.resolve_request("GET", "/nope"))

    def test_wrong_method_is_rejected(self):
        self.assertEqual(dashboard.ROUTE_METHOD_NOT_ALLOWED,
                         dashboard.resolve_request("POST", "/"))
        self.assertEqual(dashboard.ROUTE_METHOD_NOT_ALLOWED,
                         dashboard.resolve_request("POST", "/status.json"))
        self.assertEqual(dashboard.ROUTE_METHOD_NOT_ALLOWED,
                         dashboard.resolve_request("GET", "/api/refresh"))


class ResponseFormatTests(unittest.TestCase):
    def test_response_includes_status_headers_and_body(self):
        raw = dashboard.format_response(
            dashboard.STATUS_OK, dashboard.CONTENT_TYPE_JSON, b"{}")
        head, body = response_parts(raw)
        self.assertTrue(head.startswith(b"HTTP/1.1 200 OK\r\n"))
        self.assertIn(b"Content-Type: application/json; charset=utf-8", head)
        self.assertIn(b"Content-Length: 2", head)
        self.assertIn(b"Cache-Control: no-store", head)
        self.assertIn(b"Connection: close", head)
        self.assertEqual(b"{}", body)

    def test_accepts_str_body(self):
        raw = dashboard.format_response(200, dashboard.CONTENT_TYPE_TEXT, "hi")
        _head, body = response_parts(raw)
        self.assertEqual(b"hi", body)

    def test_no_content_has_empty_body(self):
        raw = dashboard.format_response(dashboard.STATUS_NO_CONTENT)
        self.assertIn(b"HTTP/1.1 204 No Content", raw)
        self.assertIn(b"Content-Length: 0", raw)

    def test_unknown_status_has_empty_reason(self):
        raw = dashboard.format_response(418)
        self.assertTrue(raw.startswith(b"HTTP/1.1 418 \r\n"))


class HandlerTests(unittest.TestCase):
    def test_serves_index_without_absolute_pressure(self):
        conn = FakeConn(b"GET / HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        head, body = response_parts(conn.written)
        self.assertTrue(head.startswith(b"HTTP/1.1 200 OK"))
        self.assertIn(b"text/html", head)
        text = body.decode("utf-8")
        self.assertIn("pressure trend", text.lower())
        self.assertIn("Refresh now", text)
        self.assertIn("/status.json", text)
        self.assertIn("temperature_f", text)
        self.assertIn("Last reading", text)
        self.assertNotIn("pressure_station", text)
        self.assertNotIn("pressure_sea_level", text)

    def test_serves_status_json(self):
        dash = make_dashboard()
        dash.update([weather_record(timestamp=1700000000)])
        conn = FakeConn(b"GET /status.json HTTP/1.1\r\n\r\n")
        dash._handle(conn)
        head, body = response_parts(conn.written)
        self.assertIn(b"application/json", head)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual("rising", payload["weather"]["trend"])
        self.assertEqual(68.0, payload["weather"]["temperature_f"])
        self.assertEqual(1700000000, payload["last_reading"])
        self.assertEqual("2023-11-14 10:13:20 PM", payload["last_reading_local"])
        self.assertNotIn("pressure", body.decode("utf-8"))

    def test_favicon_returns_no_content(self):
        conn = FakeConn(b"GET /favicon.ico HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 204"))

    def test_unknown_path_returns_not_found(self):
        conn = FakeConn(b"GET /nope HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 404"))

    def test_wrong_method_returns_method_not_allowed(self):
        conn = FakeConn(b"POST /status.json HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 405"))

    def test_malformed_request_returns_bad_request(self):
        conn = FakeConn(b"nonsense\r\n\r\n")
        make_dashboard()._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 400"))

    def test_empty_request_returns_bad_request(self):
        conn = FakeConn(b"")
        make_dashboard()._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 400"))

    def test_refresh_request_is_accepted_and_flagged(self):
        dash = make_dashboard()
        conn = FakeConn(b"POST /api/refresh HTTP/1.1\r\n\r\n")
        dash._handle(conn)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 202"))
        self.assertTrue(dash.refresh_requested)
        self.assertTrue(dash.take_refresh_request())
        self.assertFalse(dash.refresh_requested)

    def test_refresh_is_rate_limited(self):
        clock = FakeClock(0.0)
        dash = make_dashboard(clock=clock, refresh_min_interval_s=10)
        dash._handle(FakeConn(b"POST /api/refresh HTTP/1.1\r\n\r\n"))
        self.assertTrue(dash.refresh_requested)

        dash.take_refresh_request()
        clock.advance(3)
        second = FakeConn(b"POST /api/refresh HTTP/1.1\r\n\r\n")
        dash._handle(second)
        self.assertTrue(second.written.startswith(b"HTTP/1.1 200"))
        self.assertFalse(dash.refresh_requested)

        clock.advance(10)
        third = FakeConn(b"POST /api/refresh HTTP/1.1\r\n\r\n")
        dash._handle(third)
        self.assertTrue(third.written.startswith(b"HTTP/1.1 202"))
        self.assertTrue(dash.refresh_requested)

    def test_handler_does_not_touch_the_sensor(self):
        # The dashboard is only ever handed readings; it has no sensor or
        # driver reference it could read from.
        dash = make_dashboard()
        self.assertFalse(any("sensor" in name for name in vars(dash)))
        self.assertFalse(any("driver" in name for name in vars(dash)))

    def test_oversized_request_is_bounded(self):
        conn = FakeConn(b"GET /" + b"a" * 4000 + b" HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        # Read is capped at MAX_REQUEST_BYTES, so it is treated as malformed.
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 400"))

    def test_short_writes_are_retried(self):
        class ShortWriteConn(FakeConn):
            def __init__(self, request, chunk=16):
                FakeConn.__init__(self, request)
                self._chunk = chunk

            def write(self, data):
                piece = data[:self._chunk]
                self.written += piece
                return len(piece)

        conn = ShortWriteConn(b"GET / HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        head, body = response_parts(conn.written)
        self.assertTrue(head.startswith(b"HTTP/1.1 200 OK"))
        self.assertIn(b"Content-Length: %d" % len(body), head)
        self.assertTrue(body.rstrip().endswith(b"</html>"))

    def test_request_is_drained_before_the_connection_closes(self):
        # A browser sends several hundred bytes of headers. If any of them are
        # still unread when the socket is closed the stack answers with a TCP
        # RST instead of a clean FIN, and the browser can discard the (larger)
        # HTML response -- the blank page. Nothing may be left unread.
        request = (b"GET / HTTP/1.1\r\n"
                   b"Host: 10.0.0.203\r\n"
                   b"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   b"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36\r\n"
                   b"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8\r\n"
                   b"Accept-Language: en-US,en;q=0.9\r\n"
                   b"Accept-Encoding: gzip, deflate\r\n"
                   b"Connection: keep-alive\r\n"
                   b"Upgrade-Insecure-Requests: 1\r\n"
                   b"Sec-Fetch-Dest: document\r\n"
                   b"Sec-Fetch-Mode: navigate\r\n\r\n")
        self.assertGreater(len(request), 256)
        conn = FakeConn(request)
        make_dashboard()._handle(conn)
        self.assertEqual(b"", conn._in)
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 200 OK"))
        _head, body = response_parts(conn.written)
        self.assertEqual(len(dashboard.render_index_html().encode("utf-8")),
                         len(body))

    def test_short_request_is_also_fully_consumed(self):
        conn = FakeConn(b"GET /status.json HTTP/1.1\r\n\r\n")
        make_dashboard()._handle(conn)
        self.assertEqual(b"", conn._in)


class IndexPageTests(unittest.TestCase):
    """The blank-page guard: the page must be visible and its JS must parse."""

    def setUp(self):
        self.page = dashboard.render_index_html()

    def test_page_is_a_complete_non_empty_document(self):
        self.assertTrue(self.page.lstrip().startswith("<!DOCTYPE html>"))
        self.assertIn("<html", self.page)
        self.assertIn("<body>", self.page)
        self.assertTrue(self.page.rstrip().endswith("</html>"))
        self.assertGreater(len(self.page), 1000)

    def test_page_has_visible_dashboard_content(self):
        # Static defaults are rendered before any JavaScript runs, so the page
        # is never blank even if the fetch fails.
        for text in ("Clock GPS", "Pressure trend", "WAITING FOR HISTORY",
                     "Last reading", "Refresh now"):
            self.assertIn(text, self.page)
        # Nothing may be hidden wholesale.
        self.assertNotIn("display:none", self.page)
        self.assertNotIn("hidden", self.page)

    def test_page_defines_every_element_the_script_writes_to(self):
        import re

        defined = set(re.findall(r'id="([^"]+)"', self.page))
        referenced = set(re.findall(r'getElementById\("([^"]+)"\)', self.page))
        referenced |= {name for name in re.findall(r'txt\("([^"]+)"', self.page)}
        self.assertTrue(referenced)
        self.assertEqual(set(), referenced - defined)

    def test_page_tags_are_balanced(self):
        import html.parser

        class Balance(html.parser.HTMLParser):
            VOID = {"meta", "br", "hr", "img", "input", "link", "source"}

            def __init__(self):
                super().__init__()
                self.stack = []
                self.problems = []

            def handle_starttag(self, tag, attrs):
                if tag not in self.VOID:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()
                else:
                    self.problems.append(tag)

        checker = Balance()
        checker.feed(self.page)
        self.assertEqual([], checker.stack)
        self.assertEqual([], checker.problems)

    def test_script_is_valid_javascript(self):
        import re

        blocks = re.findall(r"<script>(.*?)</script>", self.page, re.S)
        self.assertEqual(1, len(blocks))
        js = blocks[0]
        self.assertTrue(js.strip())
        for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(js.count(opener), js.count(closer),
                             "unbalanced %s%s in script" % (opener, closer))
        # Inside a <script> element these sequences would end the block early.
        self.assertNotIn("</" + "script", js.lower())
        self.assertNotIn("<!--", js)
        # The expected, dependency-free browser API is used.
        self.assertIn('fetch("/status.json"', js)

    def test_script_only_reads_fields_present_in_status_json(self):
        import re

        js = re.search(r"<script>(.*?)</script>", self.page, re.S).group(1)
        payload = dashboard.build_status_payload(
            records=[weather_record()], wifi_status=FakeWifi().status(),
            now=NOW, device_id="clock-gps-01", version="0.5.0")

        def keys(node, prefix=""):
            found = set()
            for key, value in node.items():
                found.add(prefix + key)
                if isinstance(value, dict):
                    found |= keys(value, prefix + key + ".")
            return found

        available = keys(payload)
        referenced = set(re.findall(r"\bd\.([a-z_]+)", js))
        referenced |= {"weather." + name for name in re.findall(r"\bw\.([a-z_]+)", js)}
        referenced |= {"wifi." + name for name in re.findall(r"\bwf\.([a-z_]+)", js)}
        referenced |= {"sensor." + name for name in re.findall(r"\bsf\.([a-z_]+)", js)}
        self.assertTrue(referenced)
        self.assertEqual(set(), referenced - available)


class ServiceLoopTests(unittest.TestCase):
    def _running(self, events, connections, **kwargs):
        dash = make_dashboard(**kwargs)
        dash._server = FakeServer(connections)
        dash._poller = FakePoller(events)
        return dash

    def test_returns_false_when_not_started(self):
        dash = make_dashboard()
        self.assertFalse(dash.enabled)
        self.assertFalse(dash.service_until(300.0))

    def test_waits_for_the_full_deadline(self):
        dash = self._running([[]], [], clock=FakeClock(0.0))
        self.assertFalse(dash.service_until(300.0))
        self.assertEqual([300000], dash._poller.timeouts)

    def test_deadline_in_the_past_returns_immediately(self):
        dash = self._running([[]], [], clock=FakeClock(10.0))
        self.assertFalse(dash.service_until(5.0))
        self.assertEqual([], dash._poller.timeouts)

    def test_serves_a_request_then_waits_again(self):
        clock = FakeClock(0.0)
        conn = FakeConn(b"GET / HTTP/1.1\r\n\r\n")
        dash = self._running([[(0, 1)], []], [conn], clock=clock)
        self.assertFalse(dash.service_until(300.0))
        self.assertTrue(conn.written.startswith(b"HTTP/1.1 200"))
        self.assertTrue(conn.closed)
        self.assertEqual(2, len(dash._poller.timeouts))

    def test_refresh_request_stops_the_wait_early(self):
        clock = FakeClock(0.0)
        conn = FakeConn(b"POST /api/refresh HTTP/1.1\r\n\r\n")
        dash = self._running([[(0, 1)]], [conn], clock=clock)
        self.assertTrue(dash.service_until(300.0))
        self.assertEqual([300000], dash._poller.timeouts)
        self.assertEqual(1, dash._server.accepted)

    def test_poll_failure_is_not_fatal(self):
        class BrokenPoller(FakePoller):
            def poll(self, timeout_ms):
                raise OSError("boom")

        dash = make_dashboard(clock=FakeClock(0.0))
        dash._server = FakeServer([])
        dash._poller = BrokenPoller([])
        self.assertFalse(dash.service_until(300.0))

    def test_accept_failure_is_bounded_and_not_fatal(self):
        dash = self._running([[(0, 1)]], [], clock=FakeClock(0.0))
        # No pending connections: every accept() raises, so the loop must give
        # up after MAX_ACCEPT_ATTEMPTS rather than spin forever.
        self.assertFalse(dash.service_until(300.0))
        self.assertEqual(1, len(dash._poller.timeouts))


class LifecycleTests(unittest.TestCase):
    def test_disabled_start_does_not_bind(self):
        messages = []
        dash = dashboard.Dashboard(enabled=False, logger=messages.append)
        self.assertFalse(dash.start())
        self.assertEqual(["dashboard disabled"], messages)

    def test_url_uses_ip_and_omits_default_port(self):
        dash = make_dashboard()
        self.assertEqual("http://10.0.0.203", dash.url())

    def test_url_includes_non_default_port(self):
        dash = make_dashboard(port=8080)
        self.assertEqual("http://10.0.0.203:8080", dash.url())

    def test_url_without_wifi_uses_placeholder(self):
        dash = dashboard.Dashboard(wifi=None)
        self.assertEqual("http://<device-ip>", dash.url())

    def test_start_failure_is_reported_without_raising(self):
        class BrokenSocket:
            AF_INET = 2
            SOCK_STREAM = 1
            SOL_SOCKET = 1
            SO_REUSEADDR = 2

            def socket(self, *_args):
                raise OSError("no network")

        messages = []
        dash = dashboard.Dashboard(
            socket_module=BrokenSocket(), logger=messages.append)
        self.assertFalse(dash.start())
        self.assertFalse(dash.enabled)
        self.assertEqual(1, len(messages))


if __name__ == "__main__":
    unittest.main()
