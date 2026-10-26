"""OpenCitiesContentScraper's southern councils: what a one-year run fetches,
and a meeting named with a word that otherwise marks a paper as not one.

Cassettes are recorded unfiltered, so replay never sees production's shape:
one `--years` year a night. Loddon has a page per year, found from an index,
and a year must fetch the index and that year's page only, while still
returning every meeting of the year.

Hepburn held a "Confidential Meeting of Council" whose public minutes are on
its page. The base refuses any label saying "confidential", because a
confidential paper filed beside the real ones is not the meeting's minutes.
`meeting_words` lets a council say the word is part of a meeting's name. It
must not loosen the refusal anywhere else.
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
from aus_council_scrapers.scrapers.nsw.narrandera import NarranderaScraper
from aus_council_scrapers.scrapers.vic.hepburn import HepburnScraper
from aus_council_scrapers.scrapers.vic.loddon import LoddonScraper
from aus_council_scrapers.scrapers.vic.yarriambiack import YarriambiackScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_LODDON = "https://www.loddon.vic.gov.au/Our-Council/Agendas-and-minutes"


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
            LoddonScraper,
            "loddon",
            2026,
            [_LODDON, f"{_LODDON}/Agendas-and-minutes-2026"],
        ),
        (
            LoddonScraper,
            "loddon",
            2021,
            [_LODDON, f"{_LODDON}/Agendas-and-minutes-2021"],
        ),
        (
            HepburnScraper,
            "hepburn",
            2026,
            [
                "https://www.hepburn.vic.gov.au/Council/Council-meetings/Agendas-and-minutes"
            ],
        ),
        (
            YarriambiackScraper,
            "yarriambiack",
            2026,
            ["https://www.yarriambiack.vic.gov.au/Your-Council/Council-Meetings"],
        ),
        (
            NarranderaScraper,
            "narrandera",
            2025,
            [
                "https://www.narrandera.nsw.gov.au/Council/Council-meetings/"
                "Business-papers-and-minutes"
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


_PAGE = "https://council.example/Meetings"

# A closed meeting's public minutes, and a confidential paper filed beside
# an ordinary meeting's minutes.
_HTML = (
    '<div id="main-content">'
    '<a href="/files/assets/public/v/1/public-minutes-confidential-meeting-29-'
    'august-2022.pdf">Confidential Meeting of Council - Minutes - 29 August 2022</a>'
    '<a href="/files/assets/public/v/1/confidential-minutes-20-september-2022.pdf">'
    "Ordinary Meeting of Council - Confidential Minutes - 20 September 2022</a>"
    '<a href="/files/assets/public/v/1/minutes-20-september-2022.pdf">'
    "Ordinary Meeting of Council - Minutes - 20 September 2022</a>"
    "</div>"
)


class _Page:
    def fetch_with_requests(self, url, method="GET", **kwargs):
        assert url == _PAGE
        return _HTML


class _Plain(OpenCitiesContentScraper):
    pages = [ContentPage(_PAGE)]

    def __init__(self):
        super().__init__("example", "VIC", "https://council.example")


class _NamesConfidentialMeetings(_Plain):
    meeting_words = re.compile(r"\bconfidential\s+meeting\b", re.IGNORECASE)


@pytest.mark.parametrize(
    "scraper_class, meetings",
    [
        # By default "confidential" refuses both confidential papers.
        (_Plain, [("2022-09-20", "minutes-20-september-2022.pdf")]),
        # Naming the meeting keeps its minutes, and still refuses the
        # confidential paper filed under the ordinary meeting.
        (
            _NamesConfidentialMeetings,
            [
                ("2022-09-20", "minutes-20-september-2022.pdf"),
                (
                    "2022-08-29",
                    "public-minutes-confidential-meeting-29-august-2022.pdf",
                ),
            ],
        ),
    ],
)
def test_meeting_words_keep_a_meeting_named_confidential_and_nothing_else(
    scraper_class, meetings
):
    scraper = scraper_class()
    scraper.fetcher = _Page()
    with clock.frozen("2026-10-20"):
        results = scraper.scraper()
    assert [(r.date, r.minutes_url.rsplit("/", 1)[-1]) for r in results] == meetings
