"""OpenCitiesContentScraper with pages found from an index, or split by year.

Cassettes are recorded unfiltered, so replay never sees production's shape:
one `--years` year a night. A council whose year pages are found from an
index (Snowy Monaro, Torres, Bulloo) must then fetch the index and only the
pages that can hold that year, and a council split into this year's page and
an archive (South Burnett, Torres) only the side that holds it—while still
returning every meeting of the year.

An index that links no year pages is a page the scraper no longer
understands, so it must fail the council rather than report it empty. But an
index whose newest page is last year's is every January, before the council
makes the new year's page: that is a quiet start to the year, until it has
gone on too long to be one.
"""

from __future__ import annotations

import json
import re

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.opencities_content import (
    ContentPage,
    OpenCitiesContentScraper,
)
from aus_council_scrapers.scrapers.nsw.snowy_monaro import SnowyMonaroScraper
from aus_council_scrapers.scrapers.qld.bulloo import BullooScraper
from aus_council_scrapers.scrapers.qld.goondiwindi import GoondiwindiScraper
from aus_council_scrapers.scrapers.qld.south_burnett import SouthBurnettScraper
from aus_council_scrapers.scrapers.qld.torres import TorresScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_SNOWY = "https://www.snowymonaro.nsw.gov.au/Council/Meetings"
_TORRES = "https://www.torres.qld.gov.au/Council/Council-Meetings"
_GOONDIWINDI = "https://www.grc.qld.gov.au"
_SOUTH_BURNETT = (
    "https://www.southburnett.qld.gov.au/Your-Council/About-Council/Council-Meetings"
)


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
            SnowyMonaroScraper,
            "snowy_monaro",
            2025,
            [_SNOWY, f"{_SNOWY}/Business-Papers-and-Minutes-2025"],
        ),
        (
            TorresScraper,
            "torres",
            2026,
            [
                _TORRES,
                f"{_TORRES}/2026-Meeting-Agendas",
                f"{_TORRES}/2026-Meeting-Minutes",
            ],
        ),
        (
            TorresScraper,
            "torres",
            2024,
            [
                _TORRES,
                f"{_TORRES}/Archived-Meeting-Agendas",
                f"{_TORRES}/Archived-Meeting-Minutes",
            ],
        ),
        # Goondiwindi's 2021 minutes page is linked from nowhere but the
        # sitemap; nothing older than 2023 has an agenda.
        (
            GoondiwindiScraper,
            "goondiwindi",
            2021,
            [
                f"{_GOONDIWINDI}/sitemap.xml",
                f"{_GOONDIWINDI}/Council/Council-Meetings/Previous-Agendas",
                f"{_GOONDIWINDI}/Council/Council-Meetings/Previous-Meeting-Minutes"
                "/2021-Minutes",
            ],
        ),
        (SouthBurnettScraper, "south_burnett", 2026, [_SOUTH_BURNETT]),
        (
            SouthBurnettScraper,
            "south_burnett",
            2022,
            [f"{_SOUTH_BURNETT}/Previous-Council-Meetings"],
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

    # The archives come after the year pages in `pages`, so order the
    # comparison rather than the fetches.
    assert sorted(fetcher.requested) == sorted(pages)
    want = sorted(_key(r) for r in expected if parse_date(r["date"]).year == year)
    assert want, f"the {slug} cassette has no {year} meetings to compare"
    assert sorted(_key(r) for r in results) == want


_INDEX = "https://council.example/Meetings"
_ARCHIVE = "https://council.example/Meetings/Archive"


class _Pages:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.pages[url]


class _YearPages(OpenCitiesContentScraper):
    year_index = _INDEX
    year_page = re.compile(r"/Meetings-(?P<year>\d{4})$")
    pages = [ContentPage(_ARCHIVE)]

    def __init__(self):
        super().__init__("example", "QLD", "https://council.example")


def test_an_index_with_no_year_pages_fails_rather_than_reporting_the_rest():
    # A redesign that renames the year pages, or a challenge page served
    # with a 200, leaves the index with no links the pattern knows. The
    # archive still has a paper, so carrying on would report a council
    # with this year's meetings quietly missing.
    scraper = _YearPages()
    scraper.fetcher = _Pages(
        {
            _INDEX: '<div id="main-content"><a href="/About">About</a></div>',
            _ARCHIVE: (
                '<div id="main-content"><a href="/files/assets/public/v/1/'
                'agenda-15-october-2026.pdf">Ordinary Council Meeting Agenda'
                " - 15 October 2026</a></div>"
            ),
        }
    )
    scraper.years_filter = [2026]
    with clock.frozen("2026-10-20"), pytest.raises(RuntimeError, match="no year pages"):
        scraper.scraper()


@pytest.mark.parametrize(
    "scraper_class, slug",
    [
        (BullooScraper, "bulloo"),
        (TorresScraper, "torres"),
        (SnowyMonaroScraper, "snowy_monaro"),
    ],
)
def test_no_page_for_the_new_year_is_quiet_in_january_and_fails_by_april(
    scraper_class, slug
):
    # Production runs one year a night. On 6 January 2027 the index still
    # links nothing newer than 2026, so no page holds 2027: that is not a
    # broken council. By mid-April it is, and must not be reported empty.
    _, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)

    scraper = scraper_class()
    scraper.fetcher = PlaybackFetcher(replay, slug)
    scraper.years_filter = [2027]
    with clock.frozen("2027-01-06"):
        assert scraper.scraper() == []

    scraper.fetcher = PlaybackFetcher(replay, slug)
    with clock.frozen("2027-04-15"), pytest.raises(
        RuntimeError, match=r"no page holds \[2027\]"
    ):
        scraper.scraper()
