"""`years_filter` bounds the PDF reads of the councils dated from their PDFs.

Each month-only meeting of these councils costs a PDF read, a nightly
request or two each, so a run for one year must read only that year's
papers. The cassettes are recorded unfiltered; this replays
each with one year wanted and checks that the year's meetings all come back
and that no paper of a meeting in another year is read.
"""

from __future__ import annotations

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.coolamon import CoolamonScraper
from aus_council_scrapers.scrapers.nsw.warren import WarrenScraper
from aus_council_scrapers.scrapers.qld.blackall_tambo import BlackallTamboScraper
from aus_council_scrapers.scrapers.qld.boulia import BouliaScraper
from aus_council_scrapers.scrapers.qld.carpentaria import CarpentariaScraper
from aus_council_scrapers.scrapers.qld.flinders_qld import FlindersQldScraper
from aus_council_scrapers.scrapers.qld.kowanyama import KowanyamaScraper
from aus_council_scrapers.scrapers.qld.mapoon import MapoonScraper
from aus_council_scrapers.scrapers.qld.mckinlay import McKinlayScraper
from aus_council_scrapers.scrapers.qld.northern_peninsula_area import (
    NorthernPeninsulaAreaScraper,
)
from aus_council_scrapers.scrapers.qld.torres_strait_island import (
    TorresStraitIslandScraper,
)
from aus_council_scrapers.scrapers.qld.winton import WintonScraper
from aus_council_scrapers.scrapers.tas.west_coast import WestCoastTasScraper
from aus_council_scrapers.scrapers.wa.cuballing import CuballingScraper
from aus_council_scrapers.scrapers.wa.harvey import HarveyScraper
from aus_council_scrapers.scrapers.wa.murchison import MurchisonScraper
from aus_council_scrapers.scrapers.wa.woodanilling import WoodanillingScraper
from aus_council_scrapers.scrapers.wa.yalgoo import YalgooScraper
from aus_council_scrapers.scrapers.wa.yilgarn import YilgarnScraper
from tests.replay_cost import (
    CountingPlayback,
    load_cassette,
    meetings_in,
    recorded_date,
    sorted_meetings,
)

# The year each is replayed for: one with month-only meetings dated from
# their PDFs. West Coast reads nothing before 2026.
_SCRAPERS = [
    (CoolamonScraper, 2025),
    (WarrenScraper, 2025),
    (CarpentariaScraper, 2025),
    (KowanyamaScraper, 2025),
    (MapoonScraper, 2025),
    (BlackallTamboScraper, 2025),
    (BouliaScraper, 2023),
    (FlindersQldScraper, 2022),
    (McKinlayScraper, 2025),
    (NorthernPeninsulaAreaScraper, 2025),
    (TorresStraitIslandScraper, 2025),
    (WintonScraper, 2025),
    (WestCoastTasScraper, 2026),
    (CuballingScraper, 2023),
    (HarveyScraper, 2024),
    (MurchisonScraper, 2023),
    (WoodanillingScraper, 2021),
    (YalgooScraper, 2021),
    (YilgarnScraper, 2023),
]


@pytest.mark.parametrize(
    "scraper_class, year", _SCRAPERS, ids=lambda c: getattr(c, "__name__", str(c))
)
def test_one_year_reads_only_that_years_papers(scraper_class, year):
    scraper = scraper_class()
    replay, expected = load_cassette(scraper.council_name)
    fetcher = CountingPlayback(replay, scraper.council_name)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(recorded_date(replay)):
        results = [r.to_dict() for r in scraper.scraper()]

    wanted = meetings_in(expected, year)
    assert wanted, f"the cassette holds no {year} meetings to compare"
    assert sorted_meetings(results) == wanted

    other_years = {
        url
        for m in expected
        if m not in wanted
        for url in (m["agenda_url"], m["minutes_url"])
        if url
    }
    assert not other_years & set(fetcher.requested)
