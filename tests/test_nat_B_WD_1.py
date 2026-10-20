"""What `WalkerDesignsMeetingsScraper` reads for one year, and how it fails.

Cassettes are recorded unfiltered, so replay never shows what a one-year
production run fetches. Dorset is the council where that matters: a page
per year for agendas and another for minutes. Its recording is replayed with
`years_filter` set, checking both that the year's meetings all come back and
that no other year's pages are requested.

The rest are small listings that exercise the row checks the recordings
depend on (a document in the wrong column, a row with the wrong date, a
multi-part agenda), and pages the recordings do not contain: a listing that
has lost its tables, and a Dorset index that links no year pages. Each would
otherwise come back as a short or empty list that reports as a success.
"""

from __future__ import annotations

import json
import re

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.tas.dorset import DorsetScraper
from aus_council_scrapers.scrapers.tas.meander_valley import MeanderValleyScraper
from aus_council_scrapers.walkerdesigns import WalkerDesignsMeetingsScraper
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
    "scraper_cls, slug, year, max_requests",
    [
        # One listing page holds every year.
        (MeanderValleyScraper, "meander_valley", 2026, 1),
        # Two index pages, then the year's agendas page and minutes page.
        (DorsetScraper, "dorset", 2024, 4),
    ],
)
def test_one_year_returns_that_years_meetings_and_fetches_only_its_pages(
    scraper_cls, slug, year, max_requests
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
    assert len(fetcher.requested) <= max_requests
    other_years = {
        int(y)
        for url in fetcher.requested
        for y in re.findall(r"/(20\d\d)-", url)
        if int(y) != year
    }
    assert not other_years, f"fetched pages for {sorted(other_years)}"


_LISTING = "https://example.tas.gov.au/minutes-and-agendas"


class _Example(WalkerDesignsMeetingsScraper):
    listing_url = _LISTING

    def __init__(self):
        super().__init__("example_walker", "TAS", "https://example.tas.gov.au")


class _StaticFetcher:
    def __init__(self, html: str):
        self.html = html

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.html


def _doc(name: str, title: str = "") -> str:
    return (
        f'<a href="https://example.tas.gov.au/assets/{name}" '
        f'title="{title or name}"><i class="icon-file-pdf-o"></i></a>'
    )


def _table(*rows: tuple[str, str, str, str, str]) -> str:
    body = "".join(
        f'<tr class="table-secondary"><td>{d}</td><td>{m}</td><td>{a}</td>'
        f"<td>{mi}</td><td>{au}</td></tr>"
        for d, m, a, mi, au in rows
    )
    return (
        '<table class="table table-meeting"><tr class="table-primary">'
        "<th>Date</th><th>Meeting</th><th>Agenda</th><th>Minutes</th>"
        f"<th>Video/Audio</th></tr>{body}</table>"
    )


def _run(html: str, year: int = 2026, today: str = "2026-10-20") -> list[dict]:
    scraper = _Example()
    scraper.fetcher = _StaticFetcher(f"<html><body>{html}</body></html>")
    scraper.years_filter = [year]
    with clock.frozen(today):
        return [r.to_dict() for r in scraper.scraper()]


def test_a_listing_with_no_meeting_tables_fails_rather_than_returning_nothing():
    # A changed template, or a challenge page answering in its place, would
    # otherwise report as a council with no meetings, which council-alerts
    # records as a successful scrape.
    with pytest.raises(ValueError, match="no meeting tables"):
        _run("<p>Checking your browser</p>")


_LAST_YEAR_ONLY = _table(
    ("Dec 9, 2025", "Ordinary Meeting", _doc("Agenda-9-December-2025.pdf"), "", "")
)


def test_a_year_under_way_with_no_meetings_fails():
    # The newest table missing, or changed so its header no longer reads, is
    # the failure a one-year production run would otherwise report as a
    # success with 0 meetings.
    with pytest.raises(RuntimeError, match="no meetings with papers for 2026"):
        _run(_LAST_YEAR_ONLY)


def test_a_new_year_with_no_meetings_yet_only_warns(caplog):
    # In January the new year's table may not be up yet.
    assert _run(_LAST_YEAR_ONLY, today="2026-01-20") == []
    assert "no meetings with papers for 2026" in caplog.text


def test_a_header_less_schedule_table_is_not_read_as_meetings():
    schedule = "<table><tr><td>Monday</td><td>16 November</td></tr></table>"
    page = schedule + _table(
        ("Oct 13, 2026", "Ordinary Meeting", _doc("agenda-13-oct.pdf"), "", "")
    )
    assert [(r["date"], r["name"]) for r in _run(page)] == [
        ("2026-10-13", "Ordinary Meeting")
    ]


def test_minutes_filed_in_the_agenda_column_are_stored_as_minutes():
    # Meander Valley's 10 October 2023 row: the minutes in the Agenda column,
    # the Minutes column empty. Its December 2021 minutes are titled as the
    # agenda but named as minutes, and stay minutes.
    page = _table(
        (
            "Oct 13, 2026",
            "Ordinary Meeting",
            _doc("Council-Meeting-Minutes-13-October-2026.pdf"),
            "",
            "",
        ),
        (
            "Nov 10, 2026",
            "Ordinary Meeting",
            "",
            _doc("ORDINARY-Minutes-November-2026.pdf", "Ordinary Council Agenda"),
            "",
        ),
    )
    results = _run(page)
    assert [(r["agenda_url"], r["minutes_url"] is not None) for r in results] == [
        (None, True),
        (None, True),
    ]


def test_a_row_date_two_documents_contradict_is_corrected():
    # George Town's 2023 AGM row carries the ordinary meeting's date; its
    # agenda and minutes both name the real one.
    page = _table(
        (
            "Nov 28, 2026",
            "Annual General Meeting",
            _doc("2026-11-16-AGM-Agenda.pdf"),
            _doc("AGM-16-November-2026-Confirmed-Minutes.pdf"),
            "",
        )
    )
    assert [r["date"] for r in _run(page)] == ["2026-11-16"]


def test_one_document_naming_another_date_does_not_move_the_row():
    # Meander Valley's 10 September 2024 agenda says 2025 in every part.
    page = _table(
        (
            "Sep 10, 2026",
            "Ordinary Meeting",
            _doc("Agenda-10-September-2027_Part1.pdf"),
            _doc("Minutes-10-September-2026.pdf"),
            "",
        )
    )
    assert [r["date"] for r in _run(page)] == ["2026-09-10"]


def test_the_agenda_is_part_one_or_the_amended_copy_and_never_an_item():
    page = _table(
        (
            "Jan 20, 2026",
            "Ordinary Meeting",
            _doc("Agenda-20-January-2026-Part-2.pdf")
            + _doc("Agenda-20-January-2026-Part-1.pdf"),
            "",
            "",
        ),
        (
            "Feb 10, 2026",
            "Ordinary Meeting",
            _doc("Agenda-Item-9.2-Stormwater-Plan.pdf", "Agenda Item 9 2 Stormwater")
            + _doc("Agenda-10-February-2026.pdf")
            + _doc("Agenda-10-February-2026-Amended.pdf"),
            "",
            "",
        ),
        (
            "Mar 10, 2026",
            "Ordinary Meeting",
            _doc("Council-Meeting-10-March-2026.mp3"),
            "",
            "",
        ),
    )
    results = _run(page)
    # The March row holds only a recording, so it is not a meeting with papers.
    assert [r["agenda_url"].rsplit("/", 1)[-1] for r in results] == [
        "Agenda-20-January-2026-Part-1.pdf",
        "Agenda-10-February-2026-Amended.pdf",
    ]


class _DorsetIndexFetcher:
    def fetch_with_requests(self, url, method="GET", **kwargs):
        return "<html><body><p>No pages here</p></body></html>"


def test_a_dorset_index_with_no_year_pages_fails():
    scraper = DorsetScraper()
    scraper.fetcher = _DorsetIndexFetcher()
    scraper.years_filter = [2026]
    with pytest.raises(ValueError, match="no year pages"):
        scraper.scraper()


class _DorsetEmptyYearFetcher:
    # Both indexes link a 2026 page; the page has lost its cards.
    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url.endswith(("council-meeting-agendas", "council-meeting-minutes")):
            return (
                '<html><body><a class="child-listing" '
                'href="https://www.dorset.tas.gov.au/2026-x">2026</a></body></html>'
            )
        return "<html><body><p>Coming soon</p></body></html>"


def test_a_dorset_year_page_with_no_cards_fails_once_the_year_is_under_way():
    scraper = DorsetScraper()
    scraper.fetcher = _DorsetEmptyYearFetcher()
    scraper.years_filter = [2026]
    with clock.frozen("2026-10-20"):
        with pytest.raises(RuntimeError, match="no meetings with papers for 2026"):
            scraper.scraper()
