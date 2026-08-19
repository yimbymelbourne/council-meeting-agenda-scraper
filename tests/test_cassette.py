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
