"""What `DatascapeMeetingsScraper` fetches for one year, and how it fails.

Cassettes are recorded unfiltered, so replay never shows what a one-year
production run fetches, nor whether the 7 s crawl delay is kept: playback
sleeps for nothing. These tests cover those, and pages the recordings do not
contain (a listing that has lost its markup, item pages that all fail, a year
under way with no papers), each of which would otherwise come back as a
short or empty list that reports as a success.

The document rules (dates, kinds, month-only papers) are what the four
recordings pin down; they are not restated here.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock, datascape
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.datascape import (
    CRAWL_DELAY_SECONDS,
    REQUEST_TIMEOUT,
    DatascapeMeetingsScraper,
)
from aus_council_scrapers.scrapers.vic.towong import TowongScraper
from aus_council_scrapers.scrapers.wa.halls_creek import HallsCreekScraper
from aus_council_scrapers.scrapers.wa.manjimup import ManjimupScraper
from aus_council_scrapers.scrapers.wa.sandstone import SandstoneScraper
from tests.cassette import cassette_paths
from tests.test_years_filter_cost import _CountingPlayback


def _load(slug: str) -> tuple[list, list[dict]]:
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    return replay, expected


def _sorted(rows) -> list[dict]:
    return sorted(rows, key=lambda r: (r["date"], r["name"]))


@pytest.mark.parametrize(
    "scraper_cls, slug, year",
    [
        (ManjimupScraper, "manjimup", 2026),
        (TowongScraper, "towong", 2025),
        (SandstoneScraper, "sandstone", 2026),
        (HallsCreekScraper, "halls_creek", 2026),
    ],
)
def test_one_year_returns_that_years_meetings_and_reads_only_its_listing(
    scraper_cls, slug, year
):
    replay, expected = _load(slug)
    scraper = scraper_cls()
    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    want = _sorted(r for r in expected if parse_date(r["date"]).year == year)
    assert want, f"the {slug} recording has no {year} meetings to compare"
    assert _sorted(results) == want
    listings = [u for u in fetcher.requested if "year=" in u]
    assert listings and all(f"year={year}" in u for u in listings), listings
    # One listing and one page per item: well under a full run's hundred.
    assert len(fetcher.requested) <= 25


@pytest.mark.parametrize(
    "scraper_cls, slug, year, date, agenda_part, minutes_part",
    [
        # Listed for 28 August, held on 1 September (see
        # `_correct_listed_dates`).
        (
            SandstoneScraper,
            "sandstone",
            2025,
            "2025-09-01",
            "Agenda%20August%202025",
            "held%201st%20September",
        ),
        # The June 2022 meeting, held on 8 July; its papers name only the
        # month and are dated from `known_meeting_dates`.
        (
            SandstoneScraper,
            "sandstone",
            2022,
            "2022-07-08",
            "Agenda%20June%202022",
            "Minutes%20June%202022",
        ),
        # An agenda named by month only, with no minutes yet when recorded,
        # dated from its listing on a Thursday at midnight.
        (
            HallsCreekScraper,
            "halls_creek",
            2026,
            "2026-04-23",
            "OCM%20Agenda%20April%202026",
            None,
        ),
    ],
)
def test_meetings_the_listing_alone_would_misdate_or_drop(
    scraper_cls, slug, year, date, agenda_part, minutes_part
):
    replay, _ = _load(slug)
    scraper = scraper_cls()
    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = {r.date: r for r in scraper.scraper()}
    assert date in results, sorted(results)
    assert agenda_part in (results[date].agenda_url or "")
    if minutes_part:
        assert minutes_part in (results[date].minutes_url or "")
    if slug == "sandstone" and year == 2025:
        assert "2025-08-28" not in results


# --- small pages for what the recordings do not contain -------------------

_SITE = "https://example.wa.gov.au/council/meetings"


def _listing(*items: tuple[str, str, str], years=(2026, 2025)) -> str:
    options = "".join(f'<option value="{y}">{y}</option>' for y in years)
    entries = "".join(
        f'<li><a href="?item=id:{item_id}"><h2>{title}</h2>'
        f'<time datetime="{when}">x</time>'
        f'<div class="category">Council Meetings</div></a></li>'
        for item_id, title, when in items
    )
    return (
        f'<div id="meeting-listing"><form><select name="year">{options}</select>'
        f"</form><ul>{entries}</ul></div>"
    )


def _item(*papers: str) -> str:
    links = "".join(
        f'<li><a href="/repository/libraries/id:abc/hierarchy/Meetings/{p}">'
        f'<span class="name">{p}</span></a></li>'
        for p in papers
    )
    return f'<article><div id="meeting"><ul>{links}</ul></div></article>'


class _Pages(Fetcher):
    """Serves fixed pages; anything else is a failed request."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []
        self.slept: list[float] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        if url not in self.pages:
            raise ConnectionError(f"no page for {url}")
        return self.pages[url]

    def sleep(self, seconds):
        self.slept.append(seconds)

    def get_selenium_driver(self):
        raise NotImplementedError

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise NotImplementedError


class _Example(DatascapeMeetingsScraper):
    listing_url = _SITE
    category = "council-meetings"

    def __init__(self):
        super().__init__("example_datascape", "WA", "https://example.wa.gov.au")


def _listing_url(year: int) -> str:
    return f"{_SITE}?category=council-meetings&month=All&year={year}"


def _run(pages: dict[str, str], today=datetime.date(2026, 10, 20), years=(2026,)):
    scraper = _Example()
    scraper.fetcher = _Pages(pages)
    scraper.years_filter = list(years)
    with clock.frozen(today):
        return scraper, scraper.scraper()


def test_requests_to_the_site_are_kept_a_crawl_delay_apart():
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
            (
                "b",
                "Ordinary Council Meeting 27 August 2026",
                "2026-08-27T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item(
            "Agenda 24 September 2026", "Minutes 24 September 2026"
        ),
        f"{_SITE}?item=id:b": _item("Agenda 27 August 2026", "Minutes 27 August 2026"),
    }
    scraper, results = _run(pages)
    assert len(results) == 2
    # A wait before every request after the first, each close to the full
    # delay because the fake fetcher answers at once. (The first may wait
    # too, behind whatever test last used the same server.)
    later = scraper.fetcher.slept[-(len(scraper.fetcher.requested) - 1) :]
    assert len(later) == 2
    assert all(s > CRAWL_DELAY_SECONDS - 1 for s in later)


def test_councils_on_one_server_are_spaced_as_one():
    # Manjimup, Towong and Sandstone share Datascape's server, which limits
    # the client across all its sites, so the next council's first request
    # waits out the delay after the last council's last request.
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item("Agenda 24 September 2026"),
    }
    _run(pages)
    second, _ = _run(pages)
    assert len(second.fetcher.slept) == len(second.fetcher.requested) == 2
    assert all(s > CRAWL_DELAY_SECONDS - 1 for s in second.fetcher.slept)


def test_a_site_with_its_own_server_is_spaced_on_its_own():
    class _OwnServer(_Example):
        backend = None
        listing_url = "https://own.example.wa.gov.au/council/meetings"

    own_listing = (
        f"{_OwnServer.listing_url}?category=council-meetings&month=All&year=2026"
    )
    pages = {
        own_listing: _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        f"{_OwnServer.listing_url}?item=id:a": _item("Agenda 24 September 2026"),
    }
    _run(
        {
            _listing_url(2026): pages[own_listing],
            f"{_SITE}?item=id:a": _item("Agenda 24 September 2026"),
        }
    )
    scraper = _OwnServer()
    scraper.fetcher = _Pages(pages)
    scraper.years_filter = [2026]
    with clock.frozen(datetime.date(2026, 10, 20)):
        scraper.scraper()
    # Its first request does not wait behind the shared server's last one.
    assert len(scraper.fetcher.slept) == len(scraper.fetcher.requested) - 1 == 1


def test_items_far_ahead_are_not_fetched():
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
            (
                "z",
                "Ordinary Council Meeting 17 December 2026",
                "2026-12-17T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item("Agenda 24 September 2026"),
    }
    scraper, results = _run(pages)
    assert [r.date for r in results] == ["2026-09-24"]
    assert f"{_SITE}?item=id:z" not in scraper.fetcher.requested


def test_a_page_without_the_meeting_listing_raises():
    pages = {_listing_url(2026): "<html><body>Just a moment...</body></html>"}
    with pytest.raises(ValueError, match="no #meeting-listing"):
        _run(pages)


def test_a_year_whose_item_pages_all_fail_raises():
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
            (
                "b",
                "Ordinary Council Meeting 27 August 2026",
                "2026-08-27T13:00:00+08:00",
            ),
        ),
    }
    with pytest.raises(RuntimeError, match="every item page for 2026 failed"):
        _run(pages)


def test_the_current_year_with_no_papers_raises_once_it_is_under_way():
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item(),
    }
    with pytest.raises(RuntimeError, match="no Council meetings with papers in 2026"):
        _run(pages)
    # In January the same page only warns: the first meeting may not be out.
    _, results = _run(pages, today=datetime.date(2026, 1, 20))
    assert results == []


def test_a_past_year_with_no_datable_papers_only_warns():
    # Sandstone's 2022 papers are all named by month only.
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item("Agenda 24 September 2026"),
        _listing_url(2025): _listing(
            ("y", "All Council Meetings in 2025", "2025-02-01T13:00:00+08:00"),
        ),
        f"{_SITE}?item=id:y": _item("Agenda - March 2025", "Minutes - March 2025"),
    }
    _, results = _run(pages, years=(2025, 2026))
    assert [r.date for r in results] == ["2026-09-24"]


def test_years_the_filter_does_not_offer_are_not_requested():
    pages = {
        _listing_url(2025): _listing(
            (
                "a",
                "Ordinary Council Meeting 25 September 2025",
                "2025-09-25T13:00:00+08:00",
            ),
            years=(2025,),
        ),
        f"{_SITE}?item=id:a": _item("Agenda 25 September 2025"),
    }
    scraper, results = _run(
        pages, today=datetime.date(2025, 10, 20), years=(2025, 2026, 2027)
    )
    assert [r.date for r in results] == ["2025-09-25"]
    assert not any(re.search(r"year=202[67]", u) for u in scraper.fetcher.requested)


class _EmptyFirst(_Pages):
    """Answers each URL in `flaky` with an empty page the first time only.

    The sites did this a few times while being recorded (see `_page`).
    """

    def __init__(self, pages, flaky):
        super().__init__(pages)
        self.flaky = set(flaky)

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url in self.flaky:
            self.flaky.discard(url)
            self.requested.append(url)
            if "item=" in url:
                # Towong once held an item page past the read timeout.
                raise TimeoutError(f"read timed out: {url}")
            return ""
        return super().fetch_with_requests(url, method, **kwargs)


def test_an_empty_or_failed_answer_is_asked_for_again():
    item = f"{_SITE}?item=id:a"
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        item: _item("Agenda 24 September 2026", "Minutes 24 September 2026"),
    }
    scraper = _Example()
    scraper.fetcher = _EmptyFirst(pages, flaky=[_listing_url(2026), item])
    scraper.years_filter = [2026]
    with clock.frozen(datetime.date(2026, 10, 20)):
        results = scraper.scraper()
    assert [(r.date, bool(r.agenda_url), bool(r.minutes_url)) for r in results] == [
        ("2026-09-24", True, True)
    ]
    assert scraper.fetcher.requested.count(item) == 2


def test_an_item_page_that_stays_empty_is_a_failure_not_a_meeting_without_papers():
    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
            (
                "b",
                "Ordinary Council Meeting 27 August 2026",
                "2026-08-27T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": "<html><body></body></html>",
        f"{_SITE}?item=id:b": "<html><body></body></html>",
    }
    with pytest.raises(RuntimeError, match="every item page for 2026 failed"):
        _run(pages)


# --- dates the listing gets wrong, and month-only papers -----------------


def test_a_meeting_moved_after_it_was_listed_takes_the_day_its_files_name():
    # Sandstone's "2025 August" item is listed for Thursday 28 August, but
    # the meeting was held on Monday 1 September: its recording and its
    # minutes say so, and the agenda's cover does too.
    pages = {
        _listing_url(2025): _listing(
            ("a", "2025 August", "2025-08-28T13:00:00+08:00"), years=(2025,)
        ),
        f"{_SITE}?item=id:a": _item(
            "Agenda August 2025",
            "SIGNED Minutes of the Ordinary Council Meeting for August 2025 "
            "actual meeting held 1st September.pdf",
            "01-09-2025 Ordinary Council Meeting Recording September 2025.mp3",
        ),
    }
    _, results = _run(pages, today=datetime.date(2025, 10, 20), years=(2025,))
    assert [(r.date, r.time, bool(r.agenda_url), bool(r.minutes_url)) for r in results] == [
        ("2025-09-01", None, True, True)
    ]


def test_a_listed_day_with_two_rival_days_on_the_item_is_not_used(caplog):
    pages = {
        _listing_url(2025): _listing(
            ("a", "2025 August", "2025-08-28T13:00:00+08:00"), years=(2025,)
        ),
        f"{_SITE}?item=id:a": _item(
            "Agenda August 2025",
            "01-09-2025 Ordinary Council Meeting Recording.mp3",
            "04-09-2025 Ordinary Council Meeting Recording.mp3",
        ),
    }
    # Neither day is used, and with nothing else dated the year under way
    # has no papers, which fails the council rather than reporting zero.
    with pytest.raises(RuntimeError, match="no Council meetings with papers"):
        _run(pages, today=datetime.date(2025, 10, 20), years=(2025,))
    assert "left undated" in caplog.text


class _ByDocument(_Example):
    # Halls Creek's shape: an item per document, the listing Date: an upload
    # stamp except on the meeting's weekday at midnight.
    items_are_documents = True
    trust_listed_dates = False
    listed_meeting_weekday = 3


def _run_by_document(listed: list[tuple[str, str, str]], files: dict[str, str]):
    pages = {_listing_url(2026): _listing(*listed)}
    for item_id, name in files.items():
        pages[f"{_SITE}?item=id:{item_id}"] = _item(name)
    scraper = _ByDocument()
    scraper.fetcher = _Pages(pages)
    scraper.years_filter = [2026]
    with clock.frozen(datetime.date(2026, 10, 20)):
        return scraper.scraper()


def test_a_month_only_agenda_listed_on_the_meeting_weekday_at_midnight_is_dated():
    results = _run_by_document(
        [
            (
                "a",
                "Ordinary Council Meeting Agenda April 2026",
                "2026-04-23T00:00:00+08:00",
            ),
            (
                "m",
                "Ordinary Council Meeting Minutes April 2026",
                "2026-04-30T09:12:00+08:00",
            ),
        ],
        {
            "a": "OCM Agenda April 2026 14.4.26 at 0907hrs.pdf",
            "m": "OCM Minutes April 2026.pdf",
        },
    )
    # The month-only minutes join the agenda's day.
    assert [(r.date, bool(r.agenda_url), bool(r.minutes_url)) for r in results] == [
        ("2026-04-23", True, True)
    ]


@pytest.mark.parametrize(
    "when",
    [
        # An upload stamp on another day (Halls Creek's September 2026 agenda).
        "2026-09-16T00:00:00+08:00",
        # The right weekday, but with a time: an upload, not a set date.
        "2026-09-10T11:49:00+08:00",
        # A Thursday in another month.
        "2026-10-01T00:00:00+08:00",
    ],
)
def test_a_month_only_agenda_listed_any_other_way_is_left_out(when, caplog):
    # Left out with a warning. With nothing else in the year under way, the
    # council then fails rather than reporting a quiet zero.
    with pytest.raises(RuntimeError, match="no Council meetings with papers"):
        _run_by_document(
            [("a", "Ordinary Council Meeting Agenda September 2026", when)],
            {"a": "2026.09.09 Agenda OCM Sep 2026 @ 1638.pdf"},
        )
    assert "no other paper names the day" in caplog.text


def test_known_meeting_dates_date_papers_named_by_month_only():
    class _Known(_Example):
        known_meeting_dates = {
            ("ordinary", 2025, 3): datetime.date(2025, 3, 27),
        }

    pages = {
        _listing_url(2025): _listing(
            ("y", "All Council Meetings in 2025", "2025-02-01T13:00:00+08:00"),
            years=(2025,),
        ),
        f"{_SITE}?item=id:y": _item(
            "Agenda - March 2025", "Minutes - March 2025", "Agenda - April 2025"
        ),
    }
    scraper = _Known()
    scraper.fetcher = _Pages(pages)
    scraper.years_filter = [2025]
    with clock.frozen(datetime.date(2025, 10, 20)):
        results = scraper.scraper()
    # April is not in the table, so it is still left out.
    assert [(r.date, bool(r.agenda_url), bool(r.minutes_url)) for r in results] == [
        ("2025-03-27", True, True)
    ]


# --- what bounds a run's time ----------------------------------------------


def test_every_request_carries_the_shorter_read_timeout():
    class _Kwargs(_Pages):
        def fetch_with_requests(self, url, method="GET", **kwargs):
            assert kwargs.get("timeout") == REQUEST_TIMEOUT
            return super().fetch_with_requests(url, method, **kwargs)

    pages = {
        _listing_url(2026): _listing(
            (
                "a",
                "Ordinary Council Meeting 24 September 2026",
                "2026-09-24T13:00:00+08:00",
            ),
        ),
        f"{_SITE}?item=id:a": _item("Agenda 24 September 2026"),
    }
    scraper = _Example()
    scraper.fetcher = _Kwargs(pages)
    scraper.years_filter = [2026]
    with clock.frozen(datetime.date(2026, 10, 20)):
        assert len(scraper.scraper()) == 1


def test_a_council_that_waits_too_long_for_its_turn_gives_up(monkeypatch):
    monkeypatch.setattr(datascape, "MAX_TURN_WAIT_SECONDS", 0.05)
    scraper = _Example()
    scraper.fetcher = _Pages({})
    lock = datascape._backend_lock(scraper._backend_key())
    assert lock.acquire(timeout=5)
    try:
        with pytest.raises(TimeoutError, match="its turn"):
            scraper.scraper()
    finally:
        lock.release()
    # Nothing was asked of the server while it waited.
    assert scraper.fetcher.requested == []
