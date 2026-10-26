"""OpenCitiesContentScraper's month-precision councils: what a one-year run
fetches, and a sequence number that must never become a meeting's day.

Cassettes are recorded unfiltered, so replay never sees production's shape:
one `--years` year a night. Hope Vale and Temora have a page per year, found
from an index; a year must fetch the index and that year's page only (and
Temora its one Business Papers page), while still returning every meeting of
the year. Winton's archive holds 2021 and before, and is fetched only then.

These councils label most papers by month alone, and a meeting is emitted
only when its day is known. McKinlay's filenames start with a sequence
number ("05-may-...", "01-oct-...") that reads as a day; `numbered_files`
says it is not one. It must not stop a real day in a filename from counting,
and a council that does not set it keeps reading "04-april" as the 4th.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)
from aus_council_scrapers.scrapers.nsw.temora import TemoraScraper
from aus_council_scrapers.scrapers.qld.blackall_tambo import BlackallTamboScraper
from aus_council_scrapers.scrapers.qld.hope_vale import HopeValeScraper
from aus_council_scrapers.scrapers.qld.longreach import LongreachScraper
from aus_council_scrapers.scrapers.qld.mckinlay import McKinlayScraper
from aus_council_scrapers.scrapers.qld.winton import WintonScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_HOPE_VALE = "https://www.hopevale.qld.gov.au/Council/Council-Meetings"
_TEMORA = "https://www.temora.nsw.gov.au/Your-Council/Council-Meetings"
_WINTON = "https://www.winton.qld.gov.au/Council/Council-Meetings"
_BTRC = "https://www.btrc.qld.gov.au/Council/Council-Meetings"
_MCKINLAY = "https://www.mckinlay.qld.gov.au/About-Council/Council-meetings"


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _key(r: dict) -> tuple:
    return (r["date"], r["name"], r["agenda_url"] or "", r["minutes_url"] or "")


@pytest.mark.parametrize(
    "scraper_class, slug, year, pages",
    [
        (
            LongreachScraper,
            "longreach",
            2026,
            [
                "https://www.longreach.qld.gov.au/About-Council/Council/"
                "Our-Meeting-Minutes-and-Agendas"
            ],
        ),
        (
            HopeValeScraper,
            "hope_vale",
            2026,
            [_HOPE_VALE, f"{_HOPE_VALE}/2026-Meetings"],
        ),
        (
            HopeValeScraper,
            "hope_vale",
            2021,
            [_HOPE_VALE, f"{_HOPE_VALE}/2021-Meetings"],
        ),
        (
            BlackallTamboScraper,
            "blackall_tambo",
            2026,
            [f"{_BTRC}/Council-Meeting-Agendas", f"{_BTRC}/Council-Meeting-Minutes"],
        ),
        (
            McKinlayScraper,
            "mckinlay",
            2026,
            [f"{_MCKINLAY}/Meeting-Agendas", f"{_MCKINLAY}/Meeting-minutes"],
        ),
        (
            WintonScraper,
            "winton",
            2026,
            [f"{_WINTON}/Business-Papers", f"{_WINTON}/Council-Minutes"],
        ),
        (
            TemoraScraper,
            "temora",
            2026,
            [
                f"{_TEMORA}/Past-Council-Minutes",
                f"{_TEMORA}/Business-Papers",
                f"{_TEMORA}/Past-Council-Minutes/Minutes-from-2026",
            ],
        ),
    ],
)
def test_one_year_fetches_only_its_pages_and_keeps_its_meetings(
    scraper_class, slug, year, pages
):
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        fetcher = _CountingPlayback(json.load(f), slug)
    with open(result_path) as f:
        expected = json.load(f)
    scraper = scraper_class()
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    assert fetcher.requested == pages
    want = sorted(_key(r) for r in expected if parse_date(r["date"]).year == year)
    assert want, f"the {slug} cassette has no {year} meetings to compare"
    assert sorted(_key(r) for r in results) == want


@pytest.mark.parametrize(
    "scraper_class, slug, year, pages",
    [
        # Winton's 2021 meetings all give only their month. The run must
        # still read the archive, then fail rather than report a quiet year.
        (
            WintonScraper,
            "winton",
            2021,
            [f"{_WINTON}/Business-Papers", f"{_WINTON}/Previous-Agendas-and-Minutes"],
        ),
        # Temora's 2024 minutes give only their month, every one.
        (
            TemoraScraper,
            "temora",
            2024,
            [
                f"{_TEMORA}/Past-Council-Minutes",
                f"{_TEMORA}/Business-Papers",
                f"{_TEMORA}/Past-Council-Minutes/Minutes-from-2024",
            ],
        ),
    ],
)
def test_a_year_of_month_only_papers_raises(scraper_class, slug, year, pages):
    _, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        fetcher = _CountingPlayback(json.load(f), slug)
    scraper = scraper_class()
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date), pytest.raises(
        RuntimeError, match="gives its day"
    ):
        scraper.scraper()
    assert fetcher.requested == pages


_PAGE = "https://council.example/Meetings"

# An ordinary meeting's minutes labelled by month only, in a file that
# starts with the month's sequence number; a special meeting's agenda whose
# file starts with a real day; and an agenda whose zero-padded sequence
# number is not the month's.
_HTML = (
    '<div id="main-content"><div class="accordion-list-item-container">'
    '<h2 class="item-text">Meeting Papers 2024</h2>'
    '<a href="/files/assets/public/v/1/04-april-2024-ordinary-meeting-minutes.pdf">'
    "April 2024 Ordinary Meeting Minutes</a>"
    '<a href="/files/assets/public/v/1/17-january-special-meeting-agenda.pdf">'
    "January 2024 Special Meeting Agenda</a>"
    '<a href="/files/assets/public/v/1/01-oct-ordinary-meeting-agenda.pdf">'
    "October 2024 Ordinary Meeting Agenda</a>"
    "</div></div>"
)


class _Page:
    def fetch_with_requests(self, url, method="GET", **kwargs):
        assert url == _PAGE
        return _HTML


class _Plain(OpenCitiesContentScraper):
    pages = [ContentPage(_PAGE)]

    def __init__(self):
        super().__init__("example", "QLD", "https://council.example")


class _Numbered(_Plain):
    numbered_files = True


@pytest.mark.parametrize(
    "scraper_class, meetings",
    [
        # By default a day and month at the start of a file are the day.
        (
            _Plain,
            [
                ("2024-10-01", "01-oct-ordinary-meeting-agenda.pdf"),
                ("2024-04-04", "04-april-2024-ordinary-meeting-minutes.pdf"),
                ("2024-01-17", "17-january-special-meeting-agenda.pdf"),
            ],
        ),
        # With `numbered_files`, "04-april" and "01-oct" are sequence numbers,
        # so those papers give only their month and are left out; "17-january"
        # is still the 17th.
        (_Numbered, [("2024-01-17", "17-january-special-meeting-agenda.pdf")]),
    ],
)
def test_numbered_files_never_date_a_meeting_by_its_sequence_number(
    scraper_class, meetings
):
    scraper = scraper_class()
    scraper.fetcher = _Page()
    with clock.frozen("2026-10-20"):
        results = scraper.scraper()
    assert [
        (r.date, (r.agenda_url or r.minutes_url).rsplit("/", 1)[-1]) for r in results
    ] == meetings


# A month-only paper for 2026 and a dated meeting for 2025.
_MONTH_ONLY_HTML = (
    '<div id="main-content"><div class="accordion-list-item-container">'
    '<h2 class="item-text">Meeting Papers</h2>'
    '<a href="/files/assets/public/v/1/march-2026-minutes.pdf">'
    "March 2026 Council Meeting Minutes</a>"
    '<a href="/files/assets/public/v/1/minutes-18-june-2025.pdf">'
    "18 June 2025 Council Meeting Minutes</a>"
    "</div></div>"
)


class _MonthOnlyPage:
    def fetch_with_requests(self, url, method="GET", **kwargs):
        return _MONTH_ONLY_HTML


class _MonthOnlyFails(_Plain):
    month_only_fails = True


@pytest.mark.parametrize(
    "scraper_class, year, raises",
    [
        # March 2026 is on the page and cannot be dated: not a quiet year.
        (_MonthOnlyFails, 2026, True),
        # Nothing on the page for 2027 yet: a quiet January, which warns.
        (_MonthOnlyFails, 2027, False),
        # Off by default: the month-only year warns and returns nothing.
        (_Plain, 2026, False),
    ],
)
def test_month_only_fails_raises_only_for_a_year_with_undated_papers(
    scraper_class, year, raises
):
    scraper = scraper_class()
    scraper.fetcher = _MonthOnlyPage()
    scraper.years_filter = [year]
    with clock.frozen("2026-10-20"):
        if raises:
            with pytest.raises(RuntimeError, match="March 2026 Council Meeting"):
                scraper.scraper()
        else:
            assert scraper.scraper() == []
