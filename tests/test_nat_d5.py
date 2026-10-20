"""Contracts for the D-5 scrapers that cassette replay cannot see.

Replay runs each scraper unfiltered against a site that answered, so it
proves neither of the two things production depends on: that a blocked or
failing site fails the council instead of reporting it empty, and that a
one-year run (`--years 2026`, what production passes) returns that year's
meetings unchanged while fetching only what that year needs.
"""

from __future__ import annotations

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import BlockedByWAF, Fetcher
from aus_council_scrapers.scrapers.qld.aurukun import AurukunScraper
from aus_council_scrapers.scrapers.qld.mornington import MorningtonShireScraper
from aus_council_scrapers.scrapers.tas.flinders import FlindersTasScraper
from aus_council_scrapers.scrapers.wa.cranbrook import CranbrookScraper
from aus_council_scrapers.scrapers.wa.goomalling import GoomallingScraper
from aus_council_scrapers.scrapers.wa.quairading import QuairadingScraper
from aus_council_scrapers.scrapers.wa.shark_bay import SharkBayScraper
from tests.cassette import PlaybackFetcher, cassette_paths

SCRAPERS = [
    AurukunScraper,
    MorningtonShireScraper,
    FlindersTasScraper,
    CranbrookScraper,
    GoomallingScraper,
    QuairadingScraper,
    SharkBayScraper,
]


class _RefusingFetcher(Fetcher):
    """Serves the given pages, and refuses every other URL with a 403."""

    def __init__(self, pages: dict[str, str] | None = None):
        self._pages = pages or {}

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url in self._pages:
            return self._pages[url]
        raise BlockedByWAF(url, "test")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("these scrapers do not use Selenium")

    def get_selenium_driver(self):
        raise AssertionError("these scrapers do not use Selenium")

    def close(self):
        pass


@pytest.mark.parametrize("scraper_class", SCRAPERS)
def test_refused_everywhere_raises(scraper_class):
    scraper = scraper_class()
    scraper.fetcher = _RefusingFetcher()
    scraper.years_filter = [2026]
    with pytest.raises(BlockedByWAF):
        scraper.scraper()


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _run(scraper_class, years_filter=None):
    scraper = scraper_class()
    _, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        playback = _CountingPlayback(json.load(f), scraper.council_name)
    scraper.fetcher = playback
    if years_filter:
        scraper.years_filter = years_filter
    with clock.frozen(playback.recorded_date):
        results = scraper.scraper()
    return [r.to_dict() for r in results], playback.requested


def _key(record: dict):
    return (
        record["date"],
        record["name"],
        record["agenda_url"] or "",
        record["minutes_url"] or "",
    )


@pytest.mark.parametrize("scraper_class", SCRAPERS)
def test_one_year_run_returns_that_years_meetings_unchanged(scraper_class):
    # Mornington's guard against a paper borrowed from another year (the
    # "25 March 2026" agenda is the 2025 file) and Quairading's and Flinders'
    # corrections all have to hold when the other years are filtered out.
    everything, _ = _run(scraper_class)
    one_year, _ = _run(scraper_class, years_filter=[2026])
    expected = sorted((r for r in everything if r["date"].startswith("2026")), key=_key)
    assert expected, "the recording has 2026 meetings to compare"
    assert sorted(one_year, key=_key) == expected


@pytest.mark.parametrize(
    "scraper_class, other_year_marker",
    [
        # Year pages are /?meetings-in=<year> and /page/N/?meetings-in=<year>.
        (CranbrookScraper, "meetings-in=2025"),
        # Year pages are named after the year (/meetings-and-agendas-2025/).
        (AurukunScraper, "2025"),
    ],
)
def test_one_year_run_fetches_only_that_year(scraper_class, other_year_marker):
    _, unfiltered = _run(scraper_class)
    _, requested = _run(scraper_class, years_filter=[2026])
    assert any(other_year_marker in url for url in unfiltered)
    assert not any(other_year_marker in url for url in requested)
    assert len(requested) <= 3


def test_aurukun_leaves_out_a_link_the_media_endpoint_cannot_resolve():
    # An attachment page is a web page, not the PDF; emitting it as the
    # agenda would hand council-alerts HTML where a document should be.
    landing = (
        '<div id="main-content"><a href="https://www.aurukun.qld.gov.au/'
        'meetings-and-agendas-2026/">2026 Meetings</a></div>'
    )
    year_page = (
        '<div id="main-content"><div class="et_pb_text et_pb_text_1">'
        "Agenda | Ordinary Meeting | 17 March</div></div>"
        '<script>var et_link_options_data = [{"class":"et_pb_text_1",'
        '"url":"https:\\/\\/www.aurukun.qld.gov.au\\/some-attachment\\/"}];</script>'
    )

    class _Fetcher(_RefusingFetcher):
        def fetch_with_requests(self, url, method="GET", **kwargs):
            if url.endswith("/wp-json/wp/v2/media"):
                return "[]"
            return super().fetch_with_requests(url, method, **kwargs)

    scraper = AurukunScraper()
    scraper.fetcher = _Fetcher(
        {
            "https://www.aurukun.qld.gov.au/council/documents/council-minutes/": landing,
            "https://www.aurukun.qld.gov.au/meetings-and-agendas-2026/": year_page,
        }
    )
    scraper.years_filter = [2026]
    assert scraper.scraper() == []


def test_goomalling_leaves_out_a_date_cell_with_no_year():
    # dateutil fills a missing year from the real today, not the clock, so a
    # cell typed without one would be emitted under a wrong date.
    page = (
        "<h3>2026 Agendas &amp; Minutes</h3><table>"
        "<tr><td>Meeting</td><td>Date</td><td>Agenda</td><td>Minutes</td></tr>"
        "<tr><td>Ordinary</td><td>17 September</td>"
        '<td><a href="/a.pdf">Agenda - September 2026</a></td><td></td></tr>'
        "<tr><td>Ordinary</td><td>15 October 2026</td>"
        '<td><a href="/b.pdf">Agenda - October 2026</a></td><td></td></tr>'
        "</table>"
    )
    scraper = GoomallingScraper()
    scraper.fetcher = _RefusingFetcher(
        {"https://www.goomalling.wa.gov.au/council-meetings/": page}
    )
    with clock.frozen("2026-10-20"):
        dates = [r.date for r in scraper.scraper()]
    assert dates == ["2026-10-15"]


def test_flinders_reads_a_misspelt_council_minutes_label():
    # "Councl" on the live page dropped the 23 July 2025 meeting outright.
    minutes = (
        '<base href="https://www.flinders.tas.gov.au/">'
        '<a href="client-assets/m/2025.07.23.pdf">'
        "2025.07.23 Confirmed Minutes Councl Meeting</a>"
        '<a href="client-assets/m/2022.08.29.pdf">'
        "2022.08.29 Confirmed Minutes - Fin Fish Farming Public Meeting</a>"
    )
    scraper = FlindersTasScraper()
    scraper.fetcher = _RefusingFetcher(
        {
            "https://www.flinders.tas.gov.au/agendas/": "<html></html>",
            "https://www.flinders.tas.gov.au/minutes/": minutes,
        }
    )
    results = scraper.scraper()
    assert [(r.date, r.name) for r in results] == [
        ("2025-07-23", "Ordinary Council Meeting")
    ]


def test_shark_bay_reads_a_date_line_with_a_time_in_front():
    page = (
        '<div id="maincontent"><p>2022</p><p>1:00 pm 2 June 2022</p>'
        '<p><a href="/x/06June2022AuditMinutes.pdf">Minutes</a></p></div>'
    )
    scraper = SharkBayScraper()
    meetings = scraper._meetings(page, "https://www.sharkbay.wa.gov.au/aric.aspx")
    assert list(meetings) == ["2022-06-02"]
