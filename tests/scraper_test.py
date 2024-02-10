import pytest

from base_scraper import scraper_registry

from main import dynamic_import_scrapers

dynamic_import_scrapers()

@pytest.mark.parametrize("scraper_instance", scraper_registry.values(), ids=scraper_registry.keys())
def test_date_exists(scraper_instance):
    assert scraper_instance.scraper().date is not None

@pytest.mark.parametrize("scraper_instance", scraper_registry.values(), ids=scraper_registry.keys())
def test_pdf_link_exists(scraper_instance):
    assert scraper_instance.scraper().download_url is not None