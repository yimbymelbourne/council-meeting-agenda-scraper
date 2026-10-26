"""OpenCities' folder and search modes: the cases no recorded council exercises.

Lake Macquarie, Pyrenees and Queenscliffe replay folder mode against their
cassettes, and Gladstone, Central Goldfields, Queenscliffe and Wujal Wujal
replay search mode. These are the exclusions those payloads happen not to
contain, where a rule widened later would quietly store the wrong file as a
meeting's paper, plus the one production-cost contract a full-history
cassette cannot see: Gladstone's archive page is never fetched for 2026.
"""

import pytest
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.opencities import papers_by_folder, papers_by_search
from aus_council_scrapers.scrapers.qld.gladstone import _ARCHIVE_URL, GladstoneScraper
from tests.replay_cost import (
    CountingPlayback,
    load_cassette,
    meetings_in,
    recorded_date,
    sorted_meetings,
)

_BASE = "https://www.example.vic.gov.au"


def _folders(*folders: tuple[str, list[tuple[str, str]]]) -> BeautifulSoup:
    html = ""
    for title, documents in folders:
        items = "".join(
            f'<li><div class="meeting-document"><div class="meeting-document-title">'
            f'<span>{name}</span></div><div class="alt-formats">'
            f'<a href="{href}">Download PDF</a></div></div></li>'
            for name, href in documents
        )
        html += f'<div class="meeting-folder"><h3 class="folder-title">{title}</h3><ul>{items}</ul></div>'
    return BeautifulSoup(html, "html.parser")


def _sections(*sections: tuple[str, str]) -> BeautifulSoup:
    return BeautifulSoup(
        "".join(
            f'<div class="meeting-document"><h3>{heading}</h3>'
            f'<a href="{href}">Download PDF</a></div>'
            for heading, href in sections
        ),
        "html.parser",
    )


def test_a_file_titled_as_minutes_in_the_agenda_folder_is_the_minutes():
    # The title is about the one file; the folder about all of them. A
    # minutes file misfiled under "Agenda" is not the agenda, but it is still
    # the minutes when no "Minutes" folder holds one.
    content = _folders(
        (
            "Agenda",
            [
                ("March 2026 Ordinary Meeting Agenda", "/files/a/agenda.pdf"),
                ("March 2026 Ordinary Meeting Minutes", "/files/a/minutes.pdf"),
            ],
        )
    )
    assert papers_by_folder(content, _BASE) == {
        "agenda": f"{_BASE}/files/a/agenda.pdf",
        "minutes": f"{_BASE}/files/a/minutes.pdf",
    }


def test_a_business_paper_folder_holds_the_agenda():
    content = _folders(
        ("Business Paper", [("Ordinary Council Meeting", "/files/a/bp.pdf")]),
        ("Minutes", [("Ordinary Council Meeting", "/files/a/m.pdf")]),
    )
    assert papers_by_folder(content, _BASE) == {
        "agenda": f"{_BASE}/files/a/bp.pdf",
        "minutes": f"{_BASE}/files/a/m.pdf",
    }


@pytest.mark.parametrize(
    "sections, expected",
    [
        # Queenscliffe numbers each item's own paper; at present they sit in
        # nested folders, which are skipped first. A numbered item filed as
        # a section of its own must still not be the meeting's minutes.
        pytest.param(
            [
                (
                    "6.1.1 Minutes Audit & Risk Committee Meeting on 15 June 2026",
                    "/files/a/arc.pdf",
                ),
                (
                    "Ordinary Meeting of Council 22 July 2026 - Minutes",
                    "/files/a/m.pdf",
                ),
            ],
            {"minutes": f"{_BASE}/files/a/m.pdf"},
            id="an-item-numbered-heading-is-not-a-paper",
        ),
        # Heading mode's rule (Cambridge): a file named as minutes under an
        # agenda heading is the minutes, below a heading that says so.
        pytest.param(
            [
                (
                    "General Meeting Agenda 8 April 2026",
                    "/files/a/2026-04-08-minutes.pdf",
                ),
            ],
            {"minutes": f"{_BASE}/files/a/2026-04-08-minutes.pdf"},
            id="minutes-filed-under-an-agenda-heading-are-the-minutes",
        ),
        pytest.param(
            [
                (
                    "General Meeting Agenda 8 April 2026",
                    "/files/a/2026-04-08-minutes.pdf",
                ),
                ("General Meeting Minutes 8 April 2026", "/files/a/minutes.pdf"),
            ],
            {"minutes": f"{_BASE}/files/a/minutes.pdf"},
            id="and-lose-to-a-heading-that-says-minutes",
        ),
    ],
)
def test_search_mode_exclusions(sections, expected):
    assert papers_by_search(_sections(*sections), _BASE) == expected


@pytest.mark.parametrize(
    "heading",
    [
        "Special Budget Meeting Notice 21 July 2026",
        "Watch a recording of this meeting",
    ],
)
def test_the_title_rule_never_takes_a_notice_or_a_recording(heading):
    # Queenscliffe opts in so that "Planning Review Meeting 12 June 2024" is
    # its agenda; Gladstone's notices name a meeting too and are not one.
    content = _sections((heading, "/files/a/notice.pdf"))
    assert papers_by_search(content, _BASE, title_heading_agenda=True) == {}


def test_gladstone_reads_its_archive_page_only_for_the_years_it_holds():
    # The archive holds January 2024 to September 2025. Production asks for
    # 2026, and a full-history cassette cannot show that the page is then
    # never fetched.
    replay, expected = load_cassette("gladstone")
    for year, archive_wanted in ((2026, False), (2025, True)):
        fetcher = CountingPlayback(replay, "gladstone")
        scraper = GladstoneScraper()
        scraper.fetcher = fetcher
        scraper.years_filter = [year]
        with clock.frozen(recorded_date(replay)):
            results = [r.to_dict() for r in scraper.scraper()]
        assert results
        assert sorted_meetings(results) == meetings_in(expected, year)
        assert (_ARCHIVE_URL in fetcher.requested) is archive_wanted
        if year == 2025:
            # 19 August to 16 September 2025 are on both; each once.
            dates = [parse_date(r["date"]).date() for r in results]
            assert len(dates) == len(set(dates))
