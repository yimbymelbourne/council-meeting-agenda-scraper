"""
Failure-path tests for the Norwood Payneham & St Peters scraper. The cassette
replay covers the live pages; these cover a page that fails to load, which the
cassette cannot reach.
"""
import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.sa.norwood_payneham_st_peters import (
    _COMMITTEE_URL,
    NorwoodPaynehamStPetersScraper,
)

_COUNCIL_PAGE = """
<html><head><base href="https://www.npsp.sa.gov.au/"></head><body>
<div class="widget-MeetingList"><table><tbody data-year="2026">
<tr><td>Tuesday, 6 October 2026</td>
<td><a href="files/40002_2026_10_06_council_agenda.pdf?v=1">Agenda</a></td>
<td><a href="files/40041_ordinary_council_meeting_6_october_2026.pdf?v=1">Minutes</a></td></tr>
</tbody></table></div>
</body></html>
"""


class _Fetcher:
    """Serves the council page; the committee page fails or has no lists."""

    def __init__(self, committee_response):
        self.committee_response = committee_response

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url != _COMMITTEE_URL:
            return _COUNCIL_PAGE
        if isinstance(self.committee_response, Exception):
            raise self.committee_response
        return self.committee_response


def _scraper(committee_response) -> NorwoodPaynehamStPetersScraper:
    scraper = NorwoodPaynehamStPetersScraper()
    scraper.fetcher = _Fetcher(committee_response)
    scraper.years_filter = {2026}
    return scraper


def test_committee_page_failure_raises_instead_of_dropping_its_bodies():
    # The committee page is the only source for the Council Assessment
    # Panel; carrying on without it would drop that body silently.
    scraper = _scraper(requests.HTTPError("503 Server Error"))
    with clock.frozen("2026-10-19"), pytest.raises(requests.HTTPError):
        scraper.scraper()


def test_committee_page_without_meeting_lists_raises():
    scraper = _scraper("<html><body><h1>Page moved</h1></body></html>")
    with clock.frozen("2026-10-19"), pytest.raises(RuntimeError, match="layout"):
        scraper.scraper()
