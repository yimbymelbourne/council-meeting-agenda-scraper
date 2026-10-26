"""`years_filter` bounds the PDF reads of the councils dated from their PDFs.

Each meeting of Coolamon, Warren, Carpentaria, Kowanyama and Mapoon costs a
PDF read, a nightly request or two each, so a run for one year must read
only that year's papers. The cassettes are recorded unfiltered; this replays
each with one year wanted and checks that the year's meetings all come back
and that no paper of a meeting in another year is read.
"""

from __future__ import annotations

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.coolamon import CoolamonScraper
from aus_council_scrapers.scrapers.nsw.warren import WarrenScraper
from aus_council_scrapers.scrapers.qld.carpentaria import CarpentariaScraper
from aus_council_scrapers.scrapers.qld.kowanyama import KowanyamaScraper
from aus_council_scrapers.scrapers.qld.mapoon import MapoonScraper
from tests.replay_cost import (
    CountingPlayback,
    load_cassette,
    meetings_in,
    recorded_date,
    sorted_meetings,
)

_SCRAPERS = [
    CoolamonScraper,
    WarrenScraper,
    CarpentariaScraper,
    KowanyamaScraper,
    MapoonScraper,
]
_YEAR = 2025


@pytest.mark.parametrize("scraper_class", _SCRAPERS, ids=lambda c: c.__name__)
def test_one_year_reads_only_that_years_papers(scraper_class):
    scraper = scraper_class()
    replay, expected = load_cassette(scraper.council_name)
    fetcher = CountingPlayback(replay, scraper.council_name)
    scraper.fetcher = fetcher
    scraper.years_filter = [_YEAR]
    with clock.frozen(recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    wanted = meetings_in(expected, _YEAR)
    assert wanted, f"the cassette holds no {_YEAR} meetings to compare"
    assert sorted_meetings(results) == wanted

    other_years = {
        url
        for m in expected
        if m not in wanted
        for url in (m["agenda_url"], m["minutes_url"])
        if url
    }
    assert not other_years & set(fetcher.requested)
