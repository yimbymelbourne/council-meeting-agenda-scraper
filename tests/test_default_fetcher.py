"""Tests for DefaultFetcher.fetch_with_requests' retry behaviour.

Nothing else in this project's test suite exercises live-HTTP retry logic
directly -- every scraper test replays a cassette instead. These mock the
requests layer to pin down what a dropped connection actually does, rather
than relying on it working by accident during a live recording.
"""

import pytest
import requests

from aus_council_scrapers.base import DefaultFetcher


class _OKResponse:
    status_code = 200
    text = "<html>ok</html>"

    def raise_for_status(self):
        pass


def _fetcher():
    # fetch_delay=0 keeps backoff sleeps at 0 too (see __backoff), so these
    # tests don't spend real time waiting between retries.
    return DefaultFetcher(fetch_delay=0)


def test_connection_error_is_retried_and_recovers(monkeypatch):
    """A dropped connection is exactly the transient failure this fetcher
    exists to absorb (see its own class docstring: WAFs block on request
    *rate* far more often than on anything about the client) -- it must not
    abort the whole scrape on one flaky request."""
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("connection reset")
        return _OKResponse()

    monkeypatch.setattr(requests.Session, "get", fake_get)

    assert _fetcher().fetch_with_requests("https://x.test/") == "<html>ok</html>"
    assert calls["n"] == 2


def test_timeout_is_retried_the_same_way(monkeypatch):
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout("read timed out")
        return _OKResponse()

    monkeypatch.setattr(requests.Session, "get", fake_get)

    assert _fetcher().fetch_with_requests("https://x.test/") == "<html>ok</html>"
    assert calls["n"] == 2


def test_connection_error_raises_after_exhausting_retries(monkeypatch):
    """Not infinite patience -- a genuinely dead host must still fail the
    test rather than hang."""
    calls = {"n": 0}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError("connection reset")

    monkeypatch.setattr(requests.Session, "get", fake_get)

    with pytest.raises(requests.ConnectionError):
        _fetcher().fetch_with_requests("https://x.test/")
    assert calls["n"] == DefaultFetcher.MAX_RETRIES


def test_a_retryable_status_code_is_still_retried_as_before(monkeypatch):
    """The connection-error path is new; the existing status-code retry
    path (429/500/502/503/504) must be unaffected by it."""
    calls = {"n": 0}

    class _ServiceUnavailable:
        status_code = 503
        headers = {}

    def fake_get(self, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ServiceUnavailable()
        return _OKResponse()

    monkeypatch.setattr(requests.Session, "get", fake_get)

    assert _fetcher().fetch_with_requests("https://x.test/") == "<html>ok</html>"
    assert calls["n"] == 2
