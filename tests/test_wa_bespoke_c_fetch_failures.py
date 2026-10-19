"""A failed fetch must not pass for a council with no meetings.

Production asks each scraper for one year. If that year's only request fails
and the scraper logs a warning and returns [], main.py counts the council as
working with 0 meetings—the `okCouncils` blind spot AGENTS.md describes.
These scrapers raise instead when a fetch error leaves them with nothing.
"""

import pytest

from aus_council_scrapers.scrapers.wa.bayswater import BayswaterScraper
from aus_council_scrapers.scrapers.wa.cockburn import CockburnScraper
from aus_council_scrapers.scrapers.wa.fremantle import FremantleScraper
from aus_council_scrapers.scrapers.wa.mandurah import MandurahScraper
from aus_council_scrapers.scrapers.wa.mosman_park import MosmanParkScraper


class _Unreachable(Exception):
    pass


def _refuse(*args, **kwargs):
    raise _Unreachable("connection refused")


@pytest.mark.parametrize(
    "scraper_class",
    [
        BayswaterScraper,
        CockburnScraper,
        FremantleScraper,
        MandurahScraper,
        MosmanParkScraper,
    ],
)
def test_one_year_with_every_fetch_failing_raises(scraper_class, monkeypatch):
    scraper = scraper_class()
    scraper.years_filter = [2026]
    monkeypatch.setattr(scraper.fetcher, "fetch_with_requests", _refuse)
    with pytest.raises(_Unreachable):
        scraper.scraper()
