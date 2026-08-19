"""Tests for the record/replay harness itself.

The harness is what every scraper test trusts, so its leniency (or lack of
it) needs to be pinned down directly rather than inferred from scraper runs.
"""

import pytest

from tests.cassette import (
    CassetteMiss,
    PlaybackDriver,
    PlaybackFetcher,
    UnsupportedDriverCall,
    requests_key,
    should_record,
)


def test_key_omits_kwargs_slot_when_there_are_none():
    """Keys must stay identical to cassettes recorded before kwargs support."""
    assert requests_key("https://x.test/", "GET", None) == [
        "requests",
        "https://x.test/",
        "GET",
    ]
    assert requests_key("https://x.test/", "GET", {}) == [
        "requests",
        "https://x.test/",
        "GET",
    ]


def test_kwargs_are_part_of_the_key():
    a = requests_key("https://x.test/", "POST", {"data": {"year": 2024}})
    b = requests_key("https://x.test/", "POST", {"data": {"year": 2025}})
    assert a != b
    # Ordering of the kwargs dict must not change the key.
    assert requests_key("https://x.test/", "POST", {"a": 1, "b": 2}) == requests_key(
        "https://x.test/", "POST", {"b": 2, "a": 1}
    )


def test_playback_returns_recorded_response():
    fetcher = PlaybackFetcher([[["requests", "https://x.test/", "GET"], "<html>hi</html>"]])
    assert fetcher.fetch_with_requests("https://x.test/") == "<html>hi</html>"


def test_playback_raises_on_unrecorded_url():
    """The old harness returned empty HTML here, which is how scrapers
    silently lost meetings without any test noticing."""
    fetcher = PlaybackFetcher([[["requests", "https://x.test/", "GET"], "<html>hi</html>"]])
    with pytest.raises(CassetteMiss):
        fetcher.fetch_with_requests("https://x.test/?year=2020")


def test_playback_does_not_fuzzy_match_query_strings():
    fetcher = PlaybackFetcher([[["requests", "https://x.test/?year=2024", "GET"], "a"]])
    with pytest.raises(CassetteMiss):
        fetcher.fetch_with_requests("https://x.test/?year=2025")


def test_cassette_miss_survives_a_broad_except_clause():
    """Scrapers wrap fetches in `except Exception` to tolerate flaky councils.
    A missing recording must not be absorbed by that."""
    fetcher = PlaybackFetcher([])
    caught = False
    with pytest.raises(CassetteMiss):
        try:
            fetcher.fetch_with_requests("https://x.test/")
        except Exception:  # noqa: BLE001 - deliberately broad, as scrapers are
            caught = True
    assert not caught


def test_playback_sleep_is_a_noop():
    PlaybackFetcher([]).sleep(30)


def test_driver_replays_recorded_calls_in_order():
    driver = PlaybackDriver(
        [("execute_script", "click()", None), ("page_source", "", "<html>1</html>")]
    )
    driver.execute_script("click()")
    assert driver.page_source == "<html>1</html>"


def test_driver_rejects_a_different_call_sequence():
    driver = PlaybackDriver([("execute_script", "click()", None)])
    with pytest.raises(CassetteMiss):
        driver.execute_script("something_else()")


def test_driver_rejects_extra_calls():
    driver = PlaybackDriver([("page_source", "", "<html/>")])
    assert driver.page_source == "<html/>"
    with pytest.raises(CassetteMiss):
        driver.page_source


def test_driver_rejects_unreplayable_methods():
    with pytest.raises(UnsupportedDriverCall):
        PlaybackDriver([]).find_element("id", "x")


def test_driver_ops_are_separated_from_http_responses():
    fetcher = PlaybackFetcher(
        [
            [["requests", "https://x.test/", "GET"], "http"],
            [["driver", 0, "page_source", ""], "browser"],
        ]
    )
    assert fetcher.fetch_with_requests("https://x.test/") == "http"
    assert fetcher.get_selenium_driver().page_source == "browser"


def test_driver_ops_replay_in_recorded_index_order():
    """Ops are sorted by their recorded index, not by cassette file order."""
    fetcher = PlaybackFetcher(
        [
            [["driver", 1, "page_source", ""], "second"],
            [["driver", 0, "page_source", ""], "first"],
        ]
    )
    driver = fetcher.get_selenium_driver()
    assert driver.page_source == "first"
    assert driver.page_source == "second"


@pytest.mark.parametrize(
    "value,slug,expected",
    [
        ("", "waverley", False),
        ("1", "waverley", True),
        ("all", "waverley", True),
        ("waverley", "waverley", True),
        ("waverley,banyule", "banyule", True),
        ("waverley, banyule", "banyule", True),
        ("waverley", "banyule", False),
    ],
)
def test_record_flag_is_slug_scoped(monkeypatch, value, slug, expected):
    """A bare re-record of everything would sweep unrelated pending fixture
    work into whichever branch happened to run it."""
    monkeypatch.setenv("RECORD", value)
    assert should_record(slug) is expected


def test_recording_stamps_the_date_so_cassettes_do_not_expire_annually():
    """Year-range scrapers request a new URL every January. Without a pinned
    clock their cassettes fail on a calendar boundary rather than on a real
    change."""
    from aus_council_scrapers import clock
    from tests.cassette import RecordingFetcher

    class _NullFetcher:
        def fetch_with_requests(self, url, method="GET", **kwargs):
            return ""

        def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
            return ""

        def get_selenium_driver(self):
            raise NotImplementedError

        def close(self):
            pass

    with clock.frozen("2026-08-19"):
        recorder = RecordingFetcher(_NullFetcher())

    assert recorder.replay_data[0] == [["meta", "recorded_date"], "2026-08-19"]
    assert PlaybackFetcher(recorder.replay_data).recorded_date == "2026-08-19"


def test_meta_entries_are_not_served_as_responses():
    fetcher = PlaybackFetcher(
        [
            [["meta", "recorded_date"], "2026-08-19"],
            [["requests", "https://x.test/", "GET"], "body"],
        ]
    )
    assert fetcher.fetch_with_requests("https://x.test/") == "body"
    assert fetcher.recorded_date == "2026-08-19"


def test_clock_freezes_and_restores():
    from aus_council_scrapers import clock

    real = clock.current_year()
    with clock.frozen("2021-03-04"):
        assert clock.current_year() == 2021
        assert clock.today().isoformat() == "2021-03-04"
    assert clock.current_year() == real


def test_recorded_failures_are_replayed_as_failures():
    """Scrapers probe URLs that may not exist (a year page the council has
    not scheduled yet) and swallow the error. Replay must reproduce the
    failure, not invent a success."""
    import requests

    from tests.cassette import encode_failure

    failure = encode_failure(requests.HTTPError("404 Client Error for url"))
    fetcher = PlaybackFetcher([[["requests", "https://x.test/2027", "GET"], failure]])

    with pytest.raises(requests.HTTPError):
        fetcher.fetch_with_requests("https://x.test/2027")


def test_a_recorded_failure_is_distinguishable_from_a_missing_recording():
    """Both stop the scraper, but only one means the cassette is stale."""
    import requests

    from tests.cassette import encode_failure

    fetcher = PlaybackFetcher(
        [[["requests", "https://x.test/a", "GET"], encode_failure(requests.HTTPError("404"))]]
    )
    with pytest.raises(requests.HTTPError):
        fetcher.fetch_with_requests("https://x.test/a")
    with pytest.raises(CassetteMiss):
        fetcher.fetch_with_requests("https://x.test/b")


def test_a_403_is_raised_as_a_deferral_pointing_at_the_tracking_issue():
    """A firewall block is a known problem with a pending decision, so the
    error must say so rather than inviting a workaround."""
    from aus_council_scrapers.base import USER_AGENT_ISSUE, BlockedByWAF

    error = BlockedByWAF("https://www.example.vic.gov.au/meetings")
    assert USER_AGENT_ISSUE in str(error)
    assert "Do NOT work around it" in str(error)
    # Still an HTTPError, so scrapers that already tolerate fetch failures
    # keep working unchanged.
    import requests

    assert isinstance(error, requests.HTTPError)
