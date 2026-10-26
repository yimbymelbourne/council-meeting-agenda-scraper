"""Behaviour the A-IC-2 NSW InfoCouncil scrapers add on top of the base class.

Each case is a way the output went wrong, or could, without the subclass's
own handling: a meeting time read hours out, one unreadable row failing a
whole council, and an agenda left off a meeting because its link text named
only the meeting.
"""

import datetime

from bs4 import BeautifulSoup

from aus_council_scrapers.scrapers.nsw.singleton import SingletonScraper
from aus_council_scrapers.scrapers.nsw.uralla import ARCHIVE, UrallaScraper
from aus_council_scrapers.scrapers.nsw.uralla import _archive_name, _UrallaArchive
from aus_council_scrapers.scrapers.nsw.yass_valley import YassValleyScraper
from tests.cassette import PlaybackFetcher


def _grid(*rows: str) -> str:
    return f'<table id="grdMenu"><tbody>{"".join(rows)}</tbody></table>'


def _row(committee: str, date_cell: str, agenda: str) -> str:
    return f"""
      <tr>
        <td class="bpsGridCommittee">{committee}<br><span>Council Chambers</span></td>
        <td class="bpsGridDate">{date_cell}</td>
        <td class="bpsGridAgenda"><a class="bpsGridPDFLink" href="{agenda}">PDF</a></td>
        <td class="bpsGridMinutes"></td>
      </tr>
    """


class _Serve(PlaybackFetcher):
    """Serves the same page for every URL."""

    def __init__(self, html: str):
        super().__init__([])
        self._html = html

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self._html


def _scrape(scraper, html: str):
    scraper.fetcher = _Serve(html)
    scraper.years_filter = {2026}
    return scraper.scraper()


def test_dotted_times_keep_their_minutes_and_their_hour():
    # dateutil reads "5.30pm" as 17:00 and a bare "9.00" as midnight.
    results = _scrape(
        SingletonScraper(),
        _grid(
            _row("Council Meeting", "16 Nov 2026 5.30pm", "/Open/CM_16112026_AGN.PDF"),
            _row("Council Meeting", "22 Oct 2026 9.00", "/Open/CM_22102026_AGN.PDF"),
        ),
    )
    times = {r.cleaned_date: r.cleaned_time for r in results}
    assert times == {
        datetime.date(2026, 11, 16): datetime.time(17, 30),
        datetime.date(2026, 10, 22): datetime.time(9, 0),
    }


def test_yass_drops_a_row_it_cannot_date_and_keeps_the_rest():
    results = _scrape(
        YassValleyScraper(),
        _grid(
            _row("Council", "18.11.26", "/Open/OC_18112026_AGN.PDF"),
            _row("Council", "8.5.26", "/Open/OC_08052026_AGN.PDF"),
            _row("Council", "TBC", "/Open/OC_TBC_AGN.PDF"),
        ),
    )
    assert sorted(r.date for r in results) == ["2026-05-08", "2026-11-18"]


def _uralla_papers(*links: tuple[str, str]) -> dict[str, str]:
    archive = _UrallaArchive(UrallaScraper(), ARCHIVE, _archive_name)
    html = "".join(
        f'<a href="https://x/files/{href}">{label}</a>' for label, href in links
    )
    return archive.papers(BeautifulSoup(html, "html.parser"))


def test_uralla_reads_the_filename_when_the_label_names_only_the_meeting():
    papers = _uralla_papers(
        (
            "Extraordinary Meeting 1 February 2022",
            "business-paper-extraordinary-meeting-1-february-2022.pdf",
        ),
        ("Minutes Extraordinary 1 February 2022", "minutes-extraordinary.pdf"),
    )
    assert papers == {
        "agenda": "https://x/files/business-paper-extraordinary-meeting-1-february-2022.pdf",
        "minutes": "https://x/files/minutes-extraordinary.pdf",
    }


def test_uralla_does_not_let_a_filename_overrule_a_label_that_rules_a_file_out():
    papers = _uralla_papers(
        ("Tabled at the meeting", "business-paper-1-february-2022.pdf"),
    )
    assert papers == {}
