"""OpenCities' NSW vocabulary: the cases no recorded council exercises.

The seven NSW councils on `OpenCitiesMeetingsScraper` (Snowy Valleys, Broken
Hill, Bland, Gilgandra, Murrumbidgee, Central Darling, Kempsey) replay the
"Business Paper", bare-GUID and meeting-title rules against their cassettes.
These are the exclusions those payloads happen not to contain, where a rule
widened later would quietly store the wrong file as a meeting's paper.
"""

import pytest
from bs4 import BeautifulSoup

from aus_council_scrapers.opencities import papers_by_heading, papers_by_link_text
from aus_council_scrapers.scrapers.nsw.broken_hill import BrokenHillScraper
from aus_council_scrapers.scrapers.nsw.central_darling import CentralDarlingScraper
from tests.test_opencities import LISTING, _Council, _Dlv, _page

_BASE = "https://www.example.nsw.gov.au"


def _related(*links: tuple[str, str]) -> BeautifulSoup:
    items = "".join(f'<li><a href="{href}">{text}</a></li>' for text, href in links)
    return BeautifulSoup(
        f'<div class="meeting-attachments"><ul>{items}</ul></div>', "html.parser"
    )


@pytest.mark.parametrize(
    "links, expected",
    [
        pytest.param(
            [
                ("Questions on the Business Paper", "/files/a/questions.pdf"),
                ("Minutes June 2026", "/files/a/minutes.pdf"),
            ],
            {"minutes": f"{_BASE}/files/a/minutes.pdf"},
            id="questions-on-the-business-paper-is-not-the-agenda",
        ),
        pytest.param(
            [
                (
                    "Business Paper June 2026 Recording.mp3",
                    "e02abdf0-92e9-499a-bccc-e17eb7bfbfca",
                ),
            ],
            {},
            id="bare-guid-naming-a-recording-is-not-a-paper",
        ),
    ],
)
def test_link_text_exclusions(links, expected):
    assert papers_by_link_text(_related(*links), _BASE) == expected


def _sections(*sections: tuple[str, str]) -> BeautifulSoup:
    return BeautifulSoup(
        "".join(
            f'<div class="meeting-document"><h3>{heading}</h3>'
            f'<a href="{href}">Download PDF</a></div>'
            for heading, href in sections
        ),
        "html.parser",
    )


@pytest.mark.parametrize(
    "links, expected",
    [
        # Bland's separate attachment books name the business paper and
        # "attachments" in either order. Today a plain business paper sits
        # beside each, so no cassette notices if one becomes the agenda.
        pytest.param(
            [
                (
                    "Business Paper Attachments - August 2025 (PDF, 52MB)",
                    "/files/a/att.pdf",
                ),
                ("Minutes August 2025", "/files/a/m.pdf"),
            ],
            {"minutes": f"{_BASE}/files/a/m.pdf"},
            id="bland-attachments-after-business-paper-is-not-the-agenda",
        ),
        pytest.param(
            [
                (
                    "Business Paper September 2025 Attachments (PDF, 20MB)",
                    "/files/a/att.pdf",
                ),
                ("Minutes September 2025", "/files/a/m.pdf"),
            ],
            {"minutes": f"{_BASE}/files/a/m.pdf"},
            id="bland-attachments-after-the-date-is-not-the-agenda",
        ),
        pytest.param(
            [
                (
                    "Business-Paper-28-June-Item-7.3-attachments-IPR-documents-2022.pdf",
                    "/files/a/att.pdf",
                ),
            ],
            {},
            id="one-items-attachments-are-not-the-agenda",
        ),
        # A Broken Hill mayoral minute is a motion, not the meeting's minutes.
        pytest.param(
            [
                (
                    "2206-Open-Mayoral-Minute-of-Ordinary-Council-Meeting-29-June-2022.pdf",
                    "/files/a/mm.pdf",
                ),
                (
                    "2206-Open-Business-Paper-Ordinary-Council-Meeting-29-June-2022.pdf",
                    "/files/a/bp.pdf",
                ),
            ],
            {"agenda": f"{_BASE}/files/a/bp.pdf"},
            id="mayoral-minute-is-not-the-minutes",
        ),
    ],
)
def test_attachment_books_and_motions_are_not_papers(links, expected):
    # Broken Hill's own papers() adds the singular-minute rule; the others
    # are the base class's.
    scraper = BrokenHillScraper()
    scraper.base_url = _BASE
    assert scraper.papers(_related(*links)) == expected


def test_a_council_names_its_own_bound_in_business_paper():
    # Central Darling's 2025-2026 papers are the business paper with the
    # attachments bound in, labelled in Bland's attachment-book word order.
    # Only the council that names that form gets it as the agenda.
    links = _related(
        (
            "Council-Business-Paper-23-July-2025-Attachments.pdf (PDF, 12MB)",
            "/files/a/bp.pdf",
        ),
        ("Council-Minutes-23-July-2025.pdf", "/files/a/m.pdf"),
    )
    assert "agenda" not in papers_by_link_text(links, _BASE)
    scraper = CentralDarlingScraper()
    scraper.base_url = _BASE
    assert scraper.papers(links)["agenda"] == f"{_BASE}/files/a/bp.pdf"


@pytest.mark.parametrize(
    "heading",
    [
        # Onkaparinga's and Melton's headings: short, ending in "meeting",
        # and neither is an agenda.
        "Notice of adjourned meeting",
        "Record of Meeting",
        # A heading naming the minutes after the meeting.
        "Special Council Meeting Minutes",
    ],
)
def test_title_rule_never_takes_a_notice_record_or_minutes(heading):
    content = _sections((heading, "/files/a/x.pdf"))
    assert "agenda" not in papers_by_heading(content, _BASE, title_heading_agenda=True)


def test_title_rule_is_kempseys_alone():
    # "Local Traffic Committee Meeting" alone would be an agenda under the
    # rule; councils that have not opted in never read a title as a paper.
    content = _sections(("Local Traffic Committee Meeting", "/files/a/x.pdf"))
    assert papers_by_heading(content, _BASE) == {}
    assert papers_by_heading(content, _BASE, title_heading_agenda=True) == {
        "agenda": f"{_BASE}/files/a/x.pdf"
    }


def test_minutes_filed_under_an_agenda_heading_lose_to_a_minutes_heading():
    # Kempsey's 21 April 2020 replay covers the minutes being taken when
    # nothing else says "Minutes". A file named as minutes under an agenda
    # heading must still never beat a heading that says "Minutes".
    content = _sections(
        ("Agenda", "/files/a/agenda.pdf"),
        ("Agenda - 21 April 2020", "/files/a/2020-04-21-confirmed-minutes.pdf"),
        ("Minutes", "/files/a/minutes.pdf"),
    )
    assert papers_by_heading(content, _BASE) == {
        "agenda": f"{_BASE}/files/a/agenda.pdf",
        "minutes": f"{_BASE}/files/a/minutes.pdf",
    }


def test_a_row_no_year_filter_returns_is_read_off_the_bare_page():
    # Gilgandra's 20 October 2026 meeting is on the bare listing and on no
    # year's page. The cassette replays the full history, which reads the
    # bare page anyway; production asks for one year, and with a
    # year-filtered first page it would never load the bare page at all.
    year_page = LISTING + "?dlv_OC%20CL%20Public%20Meetings=(dd_OC%20Year=2026)"
    untagged = ("20 October 2026", "untagged")
    tagged = [("13 October 2026", "a"), ("15 September 2026", "b")]

    def routes(url, method, data):
        if url == year_page:
            return _page(year_page, 1, tagged, year="2026")
        if url == LISTING:
            return _page(LISTING, 1, [untagged, *tagged, ("10 December 2025", "c")])
        raise AssertionError(url)

    class _Untagged(_Dlv):
        year_filtered_first_page = True
        bare_page_rows = True

    scraper = _Untagged()
    fetcher = _Council(routes)
    scraper.fetcher = fetcher
    scraper.years_filter = [2026]

    dates = [m.date for m in scraper.scraper()]

    assert dates == ["13 October 2026", "15 September 2026", "20 October 2026"]
    assert [u for u in fetcher.requested if "cvid=" not in u] == [year_page, LISTING]
