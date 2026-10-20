"""Behaviour of the D-4 scrapers that their recorded fixtures never exercise.

The cassettes cover each parser end to end against the live pages as they
were. These cover the paths those pages did not take on the day: a Drive
folder that has gone, Duda serving HTML rather than its JSON payload, and a
Doomadgee minutes paper with only a month that no single meeting can date,
and a Cherbourg label whose hand-typed day does not exist.
"""

import datetime
import json

import pytest
import requests

from aus_council_scrapers.scrapers.nt.coomalie import CoomalieScraper
from aus_council_scrapers.scrapers.qld.cherbourg import CherbourgScraper
from aus_council_scrapers.scrapers.qld.doomadgee import DoomadgeeScraper, _Package, _Paper
from aus_council_scrapers.scrapers.tas.king_island import KingIslandScraper


class _Fetcher:
    """Answers by URL; a value that is an exception is raised."""

    def __init__(self, pages: dict):
        self.pages = pages

    def fetch_with_requests(self, url, **kwargs):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page

    def sleep(self, seconds):
        pass


_KING_ISLAND_LISTING = """
<div class="item-meeting"><p class="title">16 June 2026 Council Meeting</p>
  <div class="meeting-buttons">
    <a href="https://drive.google.com/drive/folders/AAAAAAAAAAAAAAAAAAAAAAAAA?usp=drive_link">Agenda</a>
    <a href="https://drive.google.com/file/d/BBBBBBBBBBBBBBBBBBBBBBBBB/view?usp=drive_link">Minutes</a>
  </div></div>
"""
_KING_ISLAND_FOLDER = "https://drive.google.com/drive/folders/AAAAAAAAAAAAAAAAAAAAAAAAA"


def _king_island(folder_response) -> KingIslandScraper:
    scraper = KingIslandScraper()
    scraper.years_filter = [2026]
    scraper.fetcher = _Fetcher(
        {
            "https://kingisland.tas.gov.au/council/meetings-agendas-minutes/": _KING_ISLAND_LISTING,
            _KING_ISLAND_FOLDER: folder_response,
        }
    )
    return scraper


def test_king_island_keeps_the_meeting_when_a_drive_folder_is_gone():
    gone = requests.HTTPError(f"404 Client Error: Not Found for url: {_KING_ISLAND_FOLDER}")

    (meeting,) = _king_island(gone).scraper()

    assert meeting.agenda_url is None
    assert meeting.minutes_url == (
        "https://drive.google.com/uc?export=download&id=BBBBBBBBBBBBBBBBBBBBBBBBB"
    )


def test_king_island_fails_when_drive_refuses_rather_than_losing_papers():
    refused = requests.HTTPError(f"429 Too Many Requests for url: {_KING_ISLAND_FOLDER}")

    with pytest.raises(requests.HTTPError):
        _king_island(refused).scraper()


_COOMALIE_PAGE = """
<h3>2026</h3>
<h5>19 May 2026</h5>
<p><a href="https://irp.cdn-website.com/x/files/uploaded/PUBLIC+OGM+Agenda+19+May+2026.pdf">Public OGM Agenda 19 May 2026</a></p>
<p><a href="https://irp.cdn-website.com/x/files/uploaded/Confirmed+OGM+Minutes+19+May+2026.pdf">Conf Meeting Minutes 19 May 2026</a></p>
"""


@pytest.mark.parametrize(
    "body",
    [_COOMALIE_PAGE, json.dumps({"css": "", "content": _COOMALIE_PAGE})],
    ids=["rendered-html", "duda-json-payload"],
)
def test_coomalie_reads_the_page_however_duda_serves_it(body):
    scraper = CoomalieScraper()
    scraper.years_filter = [2026]
    scraper.fetcher = _Fetcher({"https://coomalie.nt.gov.au/council-meetings": body})

    (meeting,) = scraper.scraper()

    assert (meeting.date, meeting.name) == ("2026-05-19", "Ordinary General Meeting")
    assert meeting.agenda_url.endswith("Agenda+19+May+2026.pdf")
    assert meeting.minutes_url.endswith("Minutes+19+May+2026.pdf")


def test_doomadgee_never_guesses_a_day_for_month_only_minutes():
    def paper(kind, date=None, month=None):
        return _Paper(kind, f"https://x/{kind}/{date or month}", False, date, True, month)

    papers = [
        # Two March agendas: the March minutes could belong to either.
        paper("agenda", datetime.date(2026, 3, 3)),
        paper("agenda", datetime.date(2026, 3, 31)),
        paper("minutes", month=(2026, 3)),
        # One April agenda: the April minutes are that meeting's.
        paper("agenda", datetime.date(2026, 4, 22)),
        paper("minutes", month=(2026, 4)),
    ]

    dated = DoomadgeeScraper()._date_month_only(papers)

    assert sorted((p.kind, p.date.isoformat()) for p in dated) == [
        ("agenda", "2026-03-03"),
        ("agenda", "2026-03-31"),
        ("agenda", "2026-04-22"),
        ("minutes", "2026-04-22"),
    ]


def _doomadgee_package(title, page_kind, files):
    """A package page listing `files` as (index, file name, size text)."""
    url = "https://www.doomadgee.qld.gov.au/download/pkg/"
    items = "".join(
        f'<div class="wpdm-filelist-item"><span class="wpdm-filelist-item__size">{size}</span>'
        f'<a href="{url}?wpdmdl=1&ind={index}&refresh=x&filename={name}">Download</a></div>'
        for index, name, size in files
    )
    scraper = DoomadgeeScraper()
    scraper.fetcher = _Fetcher({url: items})
    return scraper, _Package(page_kind, title, url, "1", 2025)


@pytest.mark.parametrize(
    "title, page_kind, files, expected",
    [
        # The attachment pack names the agenda, and the paper itself does
        # not say what it is: the title does.
        (
            "Council Agenda & Attachments June 16th, 2025",
            "agenda",
            [("1", "ATTACHMENTS-TO-COUNCIL-AGENDA-June-2025.pdf", "24 MB"),
             ("2", "Ordinary-Meeting-June-16-2025.pdf", "0 KB")],
            [("agenda", "2")],
        ),
        # No type word in the title either: the listing it is on decides.
        (
            "August – Confirmed Special Meeting August 29th 2025",
            "minutes",
            [("1", "Confirmed-Special-Council-Meeting-29th-August-2025.pdf", "0 KB")],
            [("minutes", "1")],
        ),
        # "Attachment-for-Minutes" is not the minutes.
        (
            "Council Agenda Special Meeting July 29, 2025",
            "agenda",
            [("1", "COUNCIL-AGENDA-SPECIAL-MEETING-29th-July-2025.pdf", "0 KB"),
             ("2", "Attachment-for-Minutes-Special-Meeting-29-July-2025.pdf", "0 KB")],
            [("agenda", "1")],
        ),
        # An upload WPDM lists as "NAN B" answers with an empty body.
        (
            "Council Agenda & Attachments August 20, 2025",
            "agenda",
            [("1", "Council-Agenda-August-25-2025.pdf", "NAN B"),
             ("2", "ATTACHMENTS-TO-COUNCIL-AGENDA-August-2025.pdf", "9 MB")],
            [],
        ),
    ],
    ids=["title-names-the-paper", "listing-names-the-paper", "minutes-attachment", "empty-upload"],
)
def test_doomadgee_classifies_package_files(title, page_kind, files, expected):
    scraper, package = _doomadgee_package(title, page_kind, files)

    papers = scraper._papers(package)

    assert [(p.kind, p.url.rsplit("ind=", 1)[1]) for p in papers] == expected


def test_doomadgee_pairs_minutes_with_the_month_their_title_names():
    scraper, package = _doomadgee_package(
        "May – Confirmed Council Minutes 4th June 2025 – For May Council Meeting",
        "minutes",
        [("1", "Confirmed-Minutes-May-Council-Ordinary-Meeting-held-4th-June-25.pdf", "0 KB")],
    )
    (minutes,) = scraper._papers(package)
    agenda = _Paper("agenda", "https://x/agenda", False, datetime.date(2025, 5, 31), True)

    meetings = DoomadgeeScraper._meetings([agenda, minutes])

    assert meetings == [(datetime.date(2025, 6, 4), False, "https://x/agenda", minutes.url)]


def test_cherbourg_skips_a_label_with_an_impossible_day():
    page = """
    <div class="appendix"><h3>Meetings Agendas, Working Papers &amp; Minutes 2025-26</h3>
      <div class="item"><a href="/wp-content/uploads/a.pdf">Download</a>
        <p class="description">Minutes 31 June</p></div>
      <div class="item"><a href="/wp-content/uploads/b.pdf">Download</a>
        <p class="description">Minutes 15 July</p></div>
    </div>
    """

    papers = CherbourgScraper()._papers(page)

    assert [(p.year, p.month, p.day) for p in papers] == [(2025, 7, 15)]
