"""DefaultFetcher's timeouts and its process-wide per-host throttle.

Both exist for production, where one process scrapes every council under a
600 s SIGKILL that discards all output (see AGENTS.md, "Where This Runs").
A request with no timeout to a silent server blocks forever, and a throttle
that only spaces one scraper's own requests lets a dozen councils on one
vendor host hit it at once.

These run against a local HTTP server rather than mocks, so they exercise
the real requests session and the real socket timeouts.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from aus_council_scrapers import base
from aus_council_scrapers.base import DefaultFetcher
from tests.cassette import RecordingFetcher


class _Server:
    """A local server that records when each request arrived.

    `/stall` accepts the request and then says nothing until released, which
    is what api.docassembler.com.au did to a local run for 12+ minutes.
    """

    def __init__(self):
        self.arrivals: list[float] = []
        self.release = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.arrivals.append(time.monotonic())
                if self.path == "/stall":
                    server.release.wait(10)
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        # The port makes each server its own throttle key, so tests never
        # see one another's reserved slots.
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def other_server():
    s = _Server()
    yield s
    s.close()


def test_a_silent_server_times_out_instead_of_hanging(server, monkeypatch):
    monkeypatch.setenv("FETCH_TIMEOUT", "0.5")
    fetcher = DefaultFetcher(fetch_delay=0)

    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        fetcher.fetch_with_requests(f"{server.url}/stall")
    assert time.monotonic() - started < 3


def test_the_default_timeout_does_not_change_cassette_keys(server):
    """Keys are built from the kwargs a scraper passes. Adding the timeout
    anywhere above DefaultFetcher would put it in every key, and every
    recorded fixture in the repo would miss on replay."""
    recorder = RecordingFetcher(DefaultFetcher(fetch_delay=0))
    url = f"{server.url}/page"

    assert recorder.fetch_with_requests(url) == "ok"
    assert recorder.replay_data[-1][0] == ["requests", url, "GET"]


def test_the_throttle_spaces_one_host_across_fetchers(server):
    """Two scrapers on one vendor host must share its FETCH_DELAY."""
    delay = 0.4
    fetchers = [DefaultFetcher(fetch_delay=delay) for _ in range(2)]

    def scrape(fetcher):
        for _ in range(2):
            fetcher.fetch_with_requests(f"{server.url}/page")

    threads = [threading.Thread(target=scrape, args=(f,)) for f in fetchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    arrivals = sorted(server.arrivals)
    assert len(arrivals) == 4
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    # The smallest jittered delay is 0.75 x FETCH_DELAY; allow for scheduling.
    assert min(gaps) > delay * 0.75 - 0.05, gaps


def test_a_shared_vendor_api_is_spaced_at_its_own_fraction(server, monkeypatch):
    """api.resolve.red serves 13 councils. At the full FETCH_DELAY their
    one-year requests alone outlast the adapter budget, so its spacing is a
    fraction of FETCH_DELAY. It is still spaced, and FETCH_DELAY still
    scales it."""
    host = server.url.split("://", 1)[1]
    monkeypatch.setitem(DefaultFetcher.HOST_DELAY_FACTORS, host, 0.25)
    delay = 1.6
    fetcher = DefaultFetcher(fetch_delay=delay)

    started = time.monotonic()
    for _ in range(3):
        fetcher.fetch_with_requests(f"{server.url}/page")
    elapsed = time.monotonic() - started

    gaps = [b - a for a, b in zip(server.arrivals, server.arrivals[1:])]
    # Spaced at 0.25 x 1.6 = 0.4 s, jittered by +/-25%, never at the full 1.6.
    assert min(gaps) > 0.4 * 0.75 - 0.05, gaps
    assert elapsed < 1.6, elapsed


def test_waiting_on_one_host_does_not_hold_up_another(server, other_server):
    """The slot is reserved under the lock but slept outside it. Sleeping
    under it would serialise every host behind the busiest one."""
    busy = DefaultFetcher(fetch_delay=1.5)
    busy.fetch_with_requests(f"{server.url}/page")
    waiting = threading.Thread(
        target=busy.fetch_with_requests, args=(f"{server.url}/page",)
    )
    waiting.start()
    time.sleep(0.1)  # let it reserve its slot and start sleeping

    started = time.monotonic()
    DefaultFetcher(fetch_delay=1.5).fetch_with_requests(f"{other_server.url}/page")
    assert time.monotonic() - started < 0.5

    waiting.join(5)


def test_selenium_gets_a_page_load_timeout(monkeypatch):
    """Chrome's default is to wait for the load event forever."""

    class FakeChrome:
        page_load_timeout = None

        def __init__(self, options=None):
            pass

        def set_page_load_timeout(self, seconds):
            self.page_load_timeout = seconds

        def execute_cdp_cmd(self, *args):
            pass

        def execute_script(self, script):
            return "Mozilla/5.0 HeadlessChrome/120"

    monkeypatch.setattr(base.webdriver, "Chrome", FakeChrome)
    driver = DefaultFetcher(fetch_delay=0).get_selenium_driver()
    assert driver.page_load_timeout == DefaultFetcher.PAGE_LOAD_TIMEOUT
