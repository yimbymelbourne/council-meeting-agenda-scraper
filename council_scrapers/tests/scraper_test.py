import pytest

from council_scrapers.base import SCRAPER_REGISTRY

@pytest.mark.parametrize("scraper_instance", SCRAPER_REGISTRY.values(), ids=SCRAPER_REGISTRY.keys())
def test_date_exists(scraper_instance):
    assert scraper_instance.scraper().date is not None

@pytest.mark.parametrize("scraper_instance", SCRAPER_REGISTRY.values(), ids=SCRAPER_REGISTRY.keys())
def test_pdf_link_exists(scraper_instance):
    assert scraper_instance.scraper().download_url is not None
