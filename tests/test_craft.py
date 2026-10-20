"""Tests for the SA Craft CMS archive base (`aus_council_scrapers/craft.py`).

The cassettes pin each council's output, but a re-record overwrites them
with whatever the code now does. These guard the rules that decide what a
document *is*, where getting it wrong puts the wrong paper in a field rather
than losing one, and the one failure no cassette contains: the WAF answering
with its challenge page instead of the archive.
"""

import datetime

import re

import pytest
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.craft import (
    CraftArchiveScraper,
    CraftMeeting,
    classify_document,
    document_links,
    parse_listing_date,
)

ASSETS = (
    "https://www.example.sa.gov.au/assets/meetings/2025/10-October/council-14-oct-2025"
)


@pytest.mark.parametrize(
    "text, expected",
    [
        # Day first: dateutil would read this as 8 October.
        ("10/08/2026 at 6:30 pm", datetime.date(2026, 8, 10)),
        ("10 Dec. 2025 at 6:30 pm", datetime.date(2025, 12, 10)),
        ("9 December 2025", datetime.date(2025, 12, 9)),
        ("03 Nov 2026 5:00pm", datetime.date(2026, 11, 3)),
        ("No date here", None),
    ],
)
def test_listing_dates_are_read_day_first(text, expected):
    assert parse_listing_date(text) == expected


@pytest.mark.parametrize(
    "label, url, by_label, expected",
    [
        ("Agenda", f"{ASSETS}/agendas/Agenda.pdf", False, "agenda"),
        ("Minutes", f"{ASSETS}/minutes/Minutes.pdf", False, "minutes"),
        # The folder outranks a misleading filename on the minutes side
        # (Playford's CAP minutes of 20 November 2025 are "...-Open-Agenda").
        ("Minutes", f"{ASSETS}/minutes/CAP-Open-Agenda.pdf", False, "minutes"),
        # Minutes uploaded into the agenda slot are not an agenda.
        ("Agenda", f"{ASSETS}/agendas/09102024-Minutes-Audit.pdf", False, None),
        ("Agenda", f"{ASSETS}/agendas/13_01_2020_-_minutes_-_ibd.pdf", False, None),
        # A combined paper names both, and is the agenda.
        ("", f"{ASSETS}/agendas/Agenda-and-Minutes-Audit.pdf", False, "agenda"),
        # Cancellations and placeholders are never a paper.
        ("CAP Notice of Cancellation", f"{ASSETS}/agendas/CAP-Notice.pdf", False, None),
        ("Agenda", f"{ASSETS}/agendas/NO-AGENDA.pdf", False, None),
        ("Supplementary Agenda", f"{ASSETS}/agendas/Supp.pdf", False, None),
        # Audio sits beside the papers at Marion.
        ("Audio", f"{ASSETS}/audio/GC-Audio.mp3", False, None),
        # Outside the paper folders, only the label pass may decide...
        ("Council Minutes", f"{ASSETS}/attachments/Council-Minutes.pdf", False, None),
        (
            "Council Minutes",
            f"{ASSETS}/attachments/Council-Minutes.pdf",
            True,
            "minutes",
        ),
        # ...and it never takes a released confidential item for the minutes.
        (
            "Confidential Release Event Minutes",
            f"{ASSETS}/attachments/Confidential-Release-Event-Minutes.pdf",
            True,
            None,
        ),
        (
            "Order of Business",
            f"{ASSETS}/order-of-business/IOBS-Agenda.pdf",
            True,
            None,
        ),
    ],
)
def test_documents_are_classified_by_folder_then_label(label, url, by_label, expected):
    assert classify_document(label, url, by_label=by_label) == expected


class _Pages(Fetcher):
    """Serves fixed HTML per URL over the requests channel."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get_selenium_driver(self):
        raise AssertionError("not used")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("not used")

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.pages[url]


class _Example(CraftArchiveScraper):
    listing_url = "https://www.example.sa.gov.au/archive"
    use_selenium = False

    def __init__(self):
        super().__init__("example_sa", "SA", "https://www.example.sa.gov.au")
        self.years_filter = [2025]

    def parse_meetings(self, soup):
        return [
            CraftMeeting(
                name=row["data-name"],
                date=parse_listing_date(row["data-date"]),
                links=[(a.get_text(), a["href"]) for a in row.find_all("a")],
            )
            for row in soup.select("div.row")
        ]


_FORM = '<select name="when"></select>'
_FIRST = f"{_Example.listing_url}?when=custom&from=2025-01-01&to=2025-12-31"
_SECOND = f"{_Example.listing_url}/p2?when=custom&from=2025-01-01&to=2025-12-31"


def _row(name: str, date: str, *docs: str) -> str:
    links = "".join(f'<a href="{ASSETS}/{doc}">x</a>' for doc in docs)
    return f'<div class="row" data-name="{name}" data-date="{date}">{links}</div>'


def test_waf_challenge_page_fails_loudly_instead_of_returning_nothing():
    # The AWS challenge is a 202 with an empty body, which the requests
    # channel returns without raising.
    scraper = _Example()
    scraper.fetcher = _Pages({_FIRST: ""})
    with pytest.raises(RuntimeError, match="WAF"):
        scraper.scraper()


def test_pages_are_followed_and_a_shared_document_stays_with_one_meeting():
    upcoming = _row("Council", "20 December 2025", "agendas/Council-20-Dec.pdf")
    scraper = _Example()
    scraper.fetcher = _Pages(
        {
            _FIRST: _FORM
            + upcoming
            + _row(
                "Council",
                "14 October 2025",
                "agendas/C-Agenda.pdf",
                "minutes/C-Min.pdf",
            )
            # Holdfast Bay uploaded that night's Council agenda into the
            # Executive Committee's slot too.
            + _row("Executive Committee", "14 October 2025", "agendas/C-Agenda.pdf")
            + '<a href="/archive/p2?when=custom">2</a>',
            # Salisbury repeats the upcoming panel on every page.
            _SECOND: _FORM
            + upcoming
            + _row("Council", "9 September 2025", "agendas/S-Agenda.pdf"),
        }
    )

    result = scraper.scraper()

    assert [(r.name, r.date) for r in result] == [
        ("Council", "2025-12-20"),
        ("Council", "2025-10-14"),
        ("Council", "2025-09-09"),
    ]
    assert result[1].minutes_url.endswith("minutes/C-Min.pdf")


@pytest.mark.parametrize(
    "meeting_date, expected",
    [
        # Playford's 22 October 2024 agenda is named "...-Open-Minutes", but
        # Craft stamped it uploaded on 17 October: it cannot be the minutes.
        (datetime.date(2024, 10, 22), "agenda"),
        # Uploaded on or after the meeting, the name is believed.
        (datetime.date(2024, 10, 17), None),
        (datetime.date(2024, 10, 15), None),
        (None, None),
    ],
)
def test_a_minutes_named_file_uploaded_before_the_meeting_stays_the_agenda(
    meeting_date, expected
):
    url = (
        f"{ASSETS}/agendas/10-Ordinary-Council-Open-Minutes_2024-10-17-004159_ogln.pdf"
    )
    assert classify_document("Agenda", url, meeting_date=meeting_date) == expected


def test_link_labels_inside_an_alpine_template_are_read():
    # Salisbury wraps each documents row in <template x-if>; BeautifulSoup
    # leaves template text out of get_text() unless asked.
    soup = BeautifulSoup(
        "<table><template><tr><td>"
        f'<a href="{ASSETS}/documents/Minutes.pdf"><span>13122021 Minutes Urban '
        "Services Committee</span> <span>(162KB PDF)</span></a>"
        "</td></tr></template></table>",
        "html.parser",
    )
    [(label, _)] = document_links(soup, ASSETS)
    assert label == "13122021 Minutes Urban Services Committee"


class _WithFallback(_Example):
    fallback_agenda_folder = re.compile(r"/order-of-business/")


def test_order_of_business_is_the_agenda_only_when_the_agendas_folder_is_empty():
    scraper = _WithFallback()
    scraper.fetcher = _Pages(
        {
            _FIRST: _FORM
            + _row(
                "Council",
                "14 October 2025",
                "order-of-business/Order-of-Business.pdf",
                "agendas/C-Agenda.pdf",
            )
            # Adelaide Hills filed the whole agenda as the order of business.
            + _row(
                "Council",
                "9 September 2025",
                "order-of-business/Council-Agenda-Public.pdf",
                "minutes/S-Min.pdf",
            )
        }
    )

    first, second = scraper.scraper()

    assert first.agenda_url.endswith("agendas/C-Agenda.pdf")
    assert second.agenda_url.endswith("order-of-business/Council-Agenda-Public.pdf")
    assert second.minutes_url.endswith("minutes/S-Min.pdf")


def test_an_archive_with_no_meetings_for_a_past_year_fails_loudly():
    # The filter form is there, so it is not the WAF, but no row parses:
    # the markup has changed. Production must not see "ok, 0 meetings".
    scraper = _Example()
    scraper.fetcher = _Pages({_FIRST: _FORM})
    with clock.frozen(datetime.date(2025, 10, 19)):
        with pytest.raises(RuntimeError, match="no meetings"):
            scraper.scraper()


def test_an_empty_archive_in_a_new_year_only_warns():
    scraper = _Example()
    scraper.fetcher = _Pages({_FIRST: _FORM})
    with clock.frozen(datetime.date(2025, 1, 6)):
        assert scraper.scraper() == []
