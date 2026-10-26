"""Residential egress: the per-scraper opt-in that routes a council through
RESIDENTIAL_PROXY_URL.

A few councils refuse GitHub's runners whatever we send, so production sends
their requests through a proxy on a home machine (AGENTS.md, "Councils that
block GitHub's runners"). The failure that matters is a quiet one: a
residential council fetched direct from a runner is refused, and before
production-safety that came back as an ok council with 0 meetings. So these
pin that an opted-in council either goes through the proxy or fails by name.

Run against local servers rather than mocks, so the real requests session
and its proxy handling are what is exercised.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aus_council_scrapers.base import (
    DefaultFetcher,
    EgressUnavailable,
    InfoCouncilScraper,
)
from aus_council_scrapers.main import run_scraper

# Never resolved: a request that reaches it only got there through the proxy.
COUNCIL_URL = "http://council.invalid/meetings"


class _Server:
    """Answers every request with "ok" and records the request line's path.

    As a proxy it sees the absolute URL (`http://council.invalid/...`); as
    the council itself it sees only the path.
    """

    def __init__(self):
        self.paths: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.paths.append(self.path)
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def proxy():
    s = _Server()
    yield s
    s.close()


def _residential(**kwargs) -> DefaultFetcher:
    return DefaultFetcher(fetch_delay=0, egress="residential", **kwargs)


def test_unset_proxy_fails_by_name_without_fetching(server, monkeypatch):
    monkeypatch.delenv("RESIDENTIAL_PROXY_URL", raising=False)
    fetcher = _residential(council="bayside_vic")

    with pytest.raises(EgressUnavailable, match="bayside_vic"):
        fetcher.fetch_with_requests(f"{server.url}/meetings")
    # And again on the next fetch: a scraper that swallowed the first error
    # must not then get through direct.
    with pytest.raises(EgressUnavailable):
        fetcher.fetch_with_requests(f"{server.url}/meetings")

    assert server.paths == []


def test_direct_means_this_machine_is_already_residential(server, monkeypatch):
    monkeypatch.setenv("RESIDENTIAL_PROXY_URL", "direct")

    assert _residential().fetch_with_requests(f"{server.url}/meetings") == "ok"
    assert server.paths == ["/meetings"]


def test_residential_requests_go_through_the_proxy(proxy, monkeypatch):
    monkeypatch.setenv("RESIDENTIAL_PROXY_URL", proxy.url)

    assert _residential().fetch_with_requests(COUNCIL_URL) == "ok"
    assert proxy.paths == [COUNCIL_URL]


def test_councils_that_did_not_opt_in_never_use_the_proxy(server, proxy, monkeypatch):
    monkeypatch.setenv("RESIDENTIAL_PROXY_URL", proxy.url)

    DefaultFetcher(fetch_delay=0).fetch_with_requests(f"{server.url}/meetings")

    assert proxy.paths == []
    assert server.paths == ["/meetings"]


def test_unreachable_proxy_fails_by_name(monkeypatch):
    # A port nothing listens on: the home machine asleep, or tinyproxy down.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("RESIDENTIAL_PROXY_URL", f"http://127.0.0.1:{port}")

    with pytest.raises(EgressUnavailable, match="did not accept a connection"):
        _residential(council="cardinia").fetch_with_requests(COUNCIL_URL)


class _ResidentialInfoCouncil(InfoCouncilScraper):
    egress = "residential"

    def __init__(self):
        super().__init__(
            "example_residential",
            "NSW",
            "https://example.nsw.gov.au",
            "https://example.infocouncil.biz/",
        )


def test_infocouncil_year_loop_does_not_swallow_it(monkeypatch):
    """The year loop catches every exception and, once all years fail,
    raises a generic RuntimeError. EgressUnavailable has to get past both."""
    monkeypatch.delenv("RESIDENTIAL_PROXY_URL", raising=False)

    with pytest.raises(EgressUnavailable):
        _ResidentialInfoCouncil().scraper()


def test_adapter_reports_the_council_as_failed_with_the_error_type(monkeypatch):
    monkeypatch.delenv("RESIDENTIAL_PROXY_URL", raising=False)

    result = run_scraper(
        _ResidentialInfoCouncil(), adapter_mode=True, skip_pdf=True, years=[2026]
    )

    assert result["ok"] is False
    assert result["council"] == "example_residential"
    assert result["error"]["type"] == "EgressUnavailable"
    assert "RESIDENTIAL_PROXY_URL is not set" in result["error"]["message"]
    assert result["egress"] == "residential"
