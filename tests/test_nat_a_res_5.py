"""Barcaldine, Palm Island and Woorabinda moved to Resolve recently and keep
their older papers on their own sites, which the scrapers do not read yet. A
run that asks only for those years must fail, not pass as a council with no
meetings."""

import pytest

from aus_council_scrapers.scrapers.qld.barcaldine import BarcaldineScraper
from aus_council_scrapers.scrapers.qld.palm_island import PalmIslandScraper
from aus_council_scrapers.scrapers.qld.woorabinda import WoorabindaScraper


@pytest.mark.parametrize(
    "scraper_class", [BarcaldineScraper, PalmIslandScraper, WoorabindaScraper]
)
def test_archive_only_year_fails(scraper_class):
    scraper = scraper_class()
    # 2020 is before each council's Resolve record, so nothing is fetched.
    scraper.years_filter = {2020}
    with pytest.raises(NotImplementedError, match=r"\[2020\]"):
        scraper.scraper()
