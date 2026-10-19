"""
Failure-path tests for the Fairfield scraper. The cassette replay covers the
live page shape; these cover what the cassette cannot reach—a failed fetch, a
reshaped table, and January's legitimately empty year.
"""
import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.fairfield import FairfieldScraper


def _page(headings: list[str], cells: list[str]) -> str:
    return (
        "<html><body><table>"
        '<tr class="bpsRowHeader">'
        + "".join(f"<th>{h}</th>" for h in headings)
        + "</tr><tr>"
        + "".join(f"<td>{c}</td>" for c in cells)
        + "</tr></table></body></html>"
    )


class _Fetcher:
    def __init__(self, response):
        self.response = response

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _scraper(response, years=(2026,)) -> FairfieldScraper:
    scraper = FairfieldScraper()
    scraper.fetcher = _Fetcher(response)
    scraper.years_filter = set(years)
    return scraper


def test_fetch_failure_raises_instead_of_returning_no_meetings():
    # Production asks for one year with one POST; swallowing its failure
    # would report the council as succeeding with 0 meetings.
    scraper = _scraper(requests.HTTPError("503 Server Error"))
    with clock.frozen("2026-10-19"), pytest.raises(requests.HTTPError):
        scraper.scraper()


def test_columns_are_found_by_heading_not_position():
    # An inserted column must not shift attachments into the agenda slot.
    page = _page(
        ["Meeting Date", "Committee", "Additional attachments", "Agendas", "Minutes"],
        [
            "13/10/2026",
            "Ordinary Council",
            '<a href="public/2026/CNL_13102026_ATT.pdf">Attachments</a>',
            '<a href="public/2026/CNL_13102026_COM_AT.pdf">Agenda</a>',
            '<a href="public/2026/CNL_13102026_MIN.pdf">Minutes</a>',
        ],
    )
    with clock.frozen("2026-10-19"):
        [meeting] = _scraper(page).scraper()
    assert meeting.agenda_url.endswith("CNL_13102026_COM_AT.pdf")
    assert meeting.minutes_url.endswith("CNL_13102026_MIN.pdf")


def test_missing_agendas_column_raises():
    page = _page(
        ["Meeting Date", "Committee", "Papers", "Minutes"],
        ["13/10/2026", "Ordinary Council", "", ""],
    )
    with clock.frozen("2026-10-19"), pytest.raises(RuntimeError, match="agendas"):
        _scraper(page).scraper()


def test_current_year_with_no_papers_yet_is_not_a_failure():
    # Fairfield's first meeting is usually in February, so for most of
    # January production's one-year request truthfully finds nothing.
    page = "<html><body>No papers published for this period</body></html>"
    with clock.frozen("2026-01-10"):
        assert _scraper(page).scraper() == []


def test_past_year_with_no_papers_raises():
    page = "<html><body>No papers published for this period</body></html>"
    with clock.frozen("2026-10-19"), pytest.raises(RuntimeError):
        _scraper(page, years=(2025,)).scraper()
