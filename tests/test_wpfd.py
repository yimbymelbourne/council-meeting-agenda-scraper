"""What `WPFileDownloadScraper` fetches for one year, and how it fails.

Cassettes are recorded unfiltered, so replay never exercises the archive
switch: a one-year production run should skip the archive page (2 MB on
Devonport) for the current year and must read it for a past one. Those cases
replay the council's own recording with `years_filter` set.

The rest are pages the recordings do not contain: a listing that has lost its
links, one that has started lazy-loading a wanted year, a month category
holding a file with a typo in its date, and West Coast's schedule page gone.
Each would otherwise come back as a short list that reports as a success.
"""

from __future__ import annotations

import json

import pytest
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.tas.central_coast_tas import CentralCoastTasScraper
from aus_council_scrapers.scrapers.tas.devonport import DevonportScraper
from aus_council_scrapers.scrapers.tas.west_coast import WestCoastTasScraper
from aus_council_scrapers.wpfd import WPFDListing, WPFileDownloadScraper
from tests.cassette import PlaybackFetcher, cassette_paths
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
    "scraper_cls, slug, year, archive_fetched",
    [
        # The current year of the recording: the archive holds nothing for it.
        (DevonportScraper, "devonport", 2026, False),
        # A past year lives only on the archive page.
        (CentralCoastTasScraper, "central_coast_tas", 2024, True),
    ],
)
def test_one_year_reads_the_archive_only_for_past_years(
    scraper_cls, slug, year, archive_fetched
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

    archive_urls = {l.url for l in scraper.listings if l.archive}
    assert bool(archive_urls & set(fetcher.requested)) is archive_fetched


_LISTING = "https://example.tas.gov.au/meetings/"


class _Example(WPFileDownloadScraper):
    listings = (WPFDListing(_LISTING),)

    def __init__(self):
        super().__init__("example_wpfd", "TAS", "https://example.tas.gov.au")


class _StaticFetcher:
    def __init__(self, html: str):
        self.html = html

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.html


def _link(category: str, file_id: int, title: str) -> str:
    slug = title.lower().replace(" ", "-")
    return (
        f'<a href="https://example.tas.gov.au/download/{category}/{file_id}/'
        f'{slug}.pdf" title="{title}">{title}</a>'
    )


def _run(html: str, year: int = 2026) -> list[dict]:
    scraper = _Example()
    scraper.fetcher = _StaticFetcher(f"<html><body>{html}</body></html>")
    scraper.years_filter = [year]
    return [r.to_dict() for r in scraper.scraper()]


def test_a_listing_with_no_download_links_fails_rather_than_returning_nothing():
    # A changed page or plugin would otherwise report as a council with no
    # meetings, which council-alerts records as a successful scrape.
    with pytest.raises(ValueError, match="no WP File Download links"):
        _run("<p>Page moved</p>")


def test_a_lazy_loaded_category_for_a_wanted_year_fails_the_scrape():
    # The plugin renders a lazy-loaded category as a placeholder link with no
    # files; its meetings would be missing from an otherwise good page.
    page = _link("10/meeting-19-october-2026", 1, "Agenda 19 October 2026") + (
        '<a class="wpfdcategory catlink" data-idcat="20" title="March 2026">'
        "March 2026</a>"
    )
    with pytest.raises(ValueError, match="lazy-loads categories.*March 2026"):
        _run(page)


def test_a_month_category_corrects_a_year_typo_and_drops_another_months_file():
    # Waratah-Wynyard has filed "Council Muinutes 20 July 2027" under its
    # July 2026 meeting. In a month category nothing outvotes the typo, so
    # unchecked it would be a 2027 meeting of its own and July 2026 would
    # have no minutes.
    page = "".join(
        [
            _link("30/july-2026", 1, "Agenda 20 July 2026"),
            _link("30/july-2026", 2, "Council Minutes 20 July 2027"),
            _link("30/july-2026", 3, "Agenda Special Council Meeting 3 August 2026"),
        ]
    )
    results = _run(page)
    assert [(r["date"], r["name"]) for r in results] == [
        ("2026-07-20", "Council Meeting")
    ]
    assert results[0]["agenda_url"].endswith("/1/agenda-20-july-2026.pdf")
    assert results[0]["minutes_url"].endswith("/2/council-minutes-20-july-2027.pdf")


class _ScheduleGone(PlaybackFetcher):
    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url == WestCoastTasScraper.schedule_url:
            return "<html><body><p>Meetings</p></body></html>"
        return super().fetch_with_requests(url, method, **kwargs)


def test_west_coast_fails_when_its_meeting_dates_schedule_is_gone():
    # Every ordinary meeting takes its day from the schedule. Without it only
    # the specials, which name their own day, would come back.
    replay, _ = _load("west_coast")
    scraper = WestCoastTasScraper()
    scraper.fetcher = _ScheduleGone(replay, "west_coast")
    with clock.frozen(scraper.fetcher.recorded_date):
        with pytest.raises(ValueError, match="no 2026 'Meeting Dates' schedule"):
            scraper.scraper()
