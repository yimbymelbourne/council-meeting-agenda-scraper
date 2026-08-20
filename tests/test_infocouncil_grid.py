"""Tests for the legacy InfoCouncil grid parser.

Agenda and minutes links share the `bpsGridPDFLink` class and are told apart
only by which cell they sit in, so the cell scoping is what keeps them
distinct. Getting it wrong invents documents rather than losing them, which
is the more damaging direction and the harder one to notice.
"""

import pytest

from aus_council_scrapers.base import InfoCouncilScraper, register_scraper
from tests.cassette import PlaybackFetcher

LISTING_URL = "https://example.infocouncil.biz/"


def _grid(rows: str) -> str:
    return f"""
    <html><body>
      <table id="grdMenu"><tbody>{rows}</tbody></table>
    </body></html>
    """


def _row(committee: str, date: str, agenda_cell: str, minutes_cell: str) -> str:
    return f"""
      <tr>
        <td class="bpsGridCommittee">{committee}<span>Town Hall</span></td>
        <td class="bpsGridDate">{date} 7:00 PM</td>
        <td class="bpsGridAgenda">{agenda_cell}</td>
        <td class="bpsGridMinutes">{minutes_cell}</td>
      </tr>
    """


PDF = '<a class="bpsGridPDFLink" href="{href}">PDF</a>'


class _Example(InfoCouncilScraper):
    def __init__(self):
        super().__init__("example", "NSW", "https://example.nsw.gov.au", LISTING_URL)


def _scrape(rows: str):
    scraper = _Example()
    # The base class walks a range of years; serve the same grid for each.
    scraper.fetcher = _AnyYear(_grid(rows))
    return scraper.scraper()


class _AnyYear(PlaybackFetcher):
    def __init__(self, html):
        super().__init__([])
        self._html = html

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self._html


def test_a_minutes_only_meeting_does_not_get_an_invented_agenda():
    """The bug this guards: minutes links carry bpsGridPDFLink too, so a
    row-wide search stored the minutes PDF as the agenda."""
    results = _scrape(
        _row("Ordinary Council", "30 Jun 2024", "", PDF.format(href="OC_MIN.PDF"))
    )
    assert results, "expected the minutes-only meeting to be returned"
    meeting = results[0]
    assert meeting.minutes_url.endswith("OC_MIN.PDF")
    assert meeting.agenda_url is None


def test_an_agenda_only_meeting_is_read_correctly():
    results = _scrape(
        _row("Ordinary Council", "30 Jun 2024", PDF.format(href="OC_AGN.PDF"), "")
    )
    assert results[0].agenda_url.endswith("OC_AGN.PDF")
    assert results[0].minutes_url is None


def test_both_documents_are_kept_apart():
    results = _scrape(
        _row(
            "Ordinary Council",
            "30 Jun 2024",
            PDF.format(href="OC_AGN.PDF"),
            PDF.format(href="OC_MIN.PDF"),
        )
    )
    meeting = results[0]
    assert meeting.agenda_url.endswith("OC_AGN.PDF")
    assert meeting.minutes_url.endswith("OC_MIN.PDF")
    assert meeting.agenda_url != meeting.minutes_url


def test_a_row_with_no_documents_is_skipped():
    assert _scrape(_row("Ordinary Council", "30 Jun 2024", "", "")) == []
