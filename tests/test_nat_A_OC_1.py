"""Production's one-year path for the eight NSW OpenCities councils of A-OC-1.

Cassettes are recorded unfiltered, so the scraper replay never runs the path
production takes: `years_filter` set to one year, `year_filtered_first_page`
fetching that year's listing page instead of the bare one, and `page_size`
folding the year into a single listing request. This replays each cassette
with the recorded year as the filter and checks both halves: the year's
meetings all come back, and the requests stay inside the per-council budget
(about 20 a year—AGENTS.md, "What keeps a run inside 600 s").
"""

from __future__ import annotations

import json

import pytest
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.opencities import ListingRow
from aus_council_scrapers.scrapers.nsw.cessnock import CessnockScraper
from aus_council_scrapers.scrapers.nsw.greater_hume import GreaterHumeScraper
from aus_council_scrapers.scrapers.nsw.kiama import KiamaScraper
from aus_council_scrapers.scrapers.nsw.lithgow import LithgowScraper
from aus_council_scrapers.scrapers.nsw.mid_coast import MidCoastScraper
from aus_council_scrapers.scrapers.nsw.mid_western import MidWesternScraper
from aus_council_scrapers.scrapers.nsw.queanbeyan_palerang import (
    QueanbeyanPalerangScraper,
)
from aus_council_scrapers.scrapers.nsw.wingecarribee import WingecarribeeScraper
from tests.cassette import PlaybackFetcher, cassette_paths

_SCRAPERS = [
    CessnockScraper,
    GreaterHumeScraper,
    KiamaScraper,
    LithgowScraper,
    MidCoastScraper,
    MidWesternScraper,
    QueanbeyanPalerangScraper,
    WingecarribeeScraper,
]

_BUDGET = 20
# QPRC meets about twice a month, every meeting a Council one: 21 payloads
# and the listing for 2026.
_OVER_BUDGET = {"queanbeyan_palerang": 22}


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _key(record: dict) -> tuple:
    return (record["date"], record["name"], record["agenda_url"] or "")


@pytest.mark.parametrize("scraper_class", _SCRAPERS, ids=lambda c: c.__name__)
def test_one_production_year_returns_that_years_meetings_within_budget(
    scraper_class,
):
    scraper = scraper_class()
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)
    recorded = next(v for k, v in replay if k == ["meta", "recorded_date"])
    year = parse_date(recorded).year

    fetcher = _CountingPlayback(replay, scraper.council_name)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    with clock.frozen(recorded):
        results = [r.to_dict() for r in scraper.scraper()]

    want = sorted((r for r in expected if parse_date(r["date"]).year == year), key=_key)
    assert want, "the cassette holds no meetings in its own year"
    assert sorted(results, key=_key) == want
    # One listing request for the year (the filtered first page, which also
    # carries the year dropdown), then one payload per kept meeting.
    listing = [u for u in fetcher.requested if "OCServiceHandler" not in u]
    assert len(listing) == 1, listing
    assert len(fetcher.requested) <= _OVER_BUDGET.get(scraper.council_name, _BUDGET)


# --------------------------------------------------------------------------
# The council-specific rules, on payloads shaped like the real ones. The
# cassettes hold the real cases, but their expected output was produced by
# this same code, so they cannot say whether the rule itself is right.
# --------------------------------------------------------------------------


def _payload(title: str, sections: list[tuple[str, str]]) -> BeautifulSoup:
    body = "".join(
        f'<div class="meeting-document"><h3>{heading}</h3>'
        f'<a href="{href}">Download PDF</a></div>'
        for heading, href in sections
    )
    return BeautifulSoup(f"<p>{title}</p>{body}", "html.parser")


def _row(date: str, meeting_type: str = "Ordinary Meeting") -> ListingRow:
    return ListingRow(date, meeting_type, "cvid", "https://x.test/listing")


_LITHGOW = "https://www.lithgow.nsw.gov.au/files/assets/public/v/1/governance/meetings"


@pytest.mark.parametrize(
    "row_date, title, folder, want_date",
    [
        # Title and folder agree against the row (12 April 2022 row).
        (
            "12 April 2022",
            "Ordinary Meeting 26 April 2022",
            "2022/26-april-2022",
            "26 April 2022",
        ),
        # Title alone disagrees; the folder backs the row (25 November 2024).
        (
            "25 November 2024",
            "Ordinary Meeting 25 November 2025",
            "2024/25-november-2024",
            "25 November 2024",
        ),
        # A misspelt folder backs nothing, so the row stands.
        (
            "25 November 2024",
            "Ordinary Meeting 25 November 2025",
            "2024/25-novermber-2024",
            "25 November 2024",
        ),
    ],
)
def test_lithgow_uses_the_titles_date_only_when_the_folder_agrees(
    row_date, title, folder, want_date
):
    agenda = f"{_LITHGOW}/{folder}/agenda.pdf"
    record = LithgowScraper().build_return(
        _payload(title, [("Agenda", agenda)]), _row(row_date)
    )
    assert record.date == want_date
    assert record.agenda_url == agenda


@pytest.mark.parametrize(
    "scraper_class, row_date, url, kept",
    [
        # Folder and file name both name another meeting (Lithgow 6 April
        # 2020, Mid-Western 14 August 2024): not this meeting's paper.
        (
            LithgowScraper,
            "06 April 2020",
            f"{_LITHGOW}/2020/9-march-2020/minutes-9-march-2020.pdf",
            False,
        ),
        (
            MidWesternScraper,
            "14 August 2024",
            "https://www.midwestern.nsw.gov.au/files/assets/public/v/1/council-meetings"
            "/old/2024/10.-16-october-2024/business-paper-16-october-2024.pdf",
            False,
        ),
        # Re-published into a later folder, its own date in its name
        # (Mid-Western 9 December 2020): still this meeting's.
        (
            MidWesternScraper,
            "09 December 2020",
            "https://www.midwestern.nsw.gov.au/files/assets/public/v/1/council-meetings"
            "/2021/10.-4-august-2021/council-meeting-9-december-2020-business-paper.pdf",
            True,
        ),
        # Right folder, wrong name (Mid-Western 13 October 2021): kept.
        (
            MidWesternScraper,
            "13 October 2021",
            "https://www.midwestern.nsw.gov.au/files/assets/public/v/1/council-meetings"
            "/old/2021/12.13-october-2021/council-meeting-4-august-2021-minutes.pdf",
            True,
        ),
    ],
)
def test_a_paper_is_dropped_only_when_folder_and_name_both_say_another_date(
    scraper_class, row_date, url, kept
):
    scraper = scraper_class()
    content = _payload("Ordinary Council Meeting", [("Minutes", url)])
    papers = scraper.row_papers(content, _row(row_date))
    # Kept papers may come back at a corrected address (Mid-Western's old/).
    assert ("minutes" in papers) is kept


def test_queanbeyan_palerang_reads_body_first_headings_and_skips_public_forum():
    base = "https://www.qprc.nsw.gov.au/files/"
    content = _payload(
        "",
        [
            ("Extraordinary Meeting Agenda", base + "agenda.pdf"),
            ("Minutes - Public Forum", base + "forum-minutes.pdf"),
            ("Ordinary Minutes", base + "ordinary-minutes.pdf"),
        ],
    )
    assert QueanbeyanPalerangScraper().papers(content) == {
        "agenda": base + "agenda.pdf",
        "minutes": base + "ordinary-minutes.pdf",
    }


def test_mid_western_reports_moved_papers_at_their_working_address():
    # 20 July 2022's agenda answers 404 where the payload links it and 200
    # with old/ inserted (October 2026); 2024 onwards are linked correctly.
    folder = (
        "https://www.midwestern.nsw.gov.au/files/assets/public/v/1/council-meetings"
    )
    content = _payload(
        "Ordinary Council Meeting",
        [("Agenda 20 July 2022", f"{folder}/2022/09.-20-july-2022/agenda.pdf")],
    )
    assert MidWesternScraper().row_papers(content, _row("20 July 2022")) == {
        "agenda": f"{folder}/old/2022/09.-20-july-2022/agenda.pdf"
    }
    content = _payload(
        "Ordinary Council Meeting",
        [("Agenda 18 June 2025", f"{folder}/2025/6.-18-june-2025/agenda.pdf")],
    )
    assert MidWesternScraper().row_papers(content, _row("18 June 2025")) == {
        "agenda": f"{folder}/2025/6.-18-june-2025/agenda.pdf"
    }


def test_cessnock_reads_the_plural_agendas_heading():
    # 16 February 2022 files its PDF agenda under "Agendas and enclosures";
    # the base rule's agenda\b does not match the plural.
    base = "https://www.cessnock.nsw.gov.au/files/"
    content = _payload(
        "",
        [
            ("Agendas and enclosures", base + "agenda-and-enclosures.pdf"),
            ("Minutes", base + "minutes.pdf"),
        ],
    )
    assert CessnockScraper().papers(content) == {
        "agenda": base + "agenda-and-enclosures.pdf",
        "minutes": base + "minutes.pdf",
    }


@pytest.mark.parametrize(
    "links, want_minutes",
    [
        # 14 December 2023: the singular label is the meeting's only minutes.
        ([("Minute as amended - 14 December 2023", "amended.pdf")], "amended.pdf"),
        # A plain "Minutes" still outranks an amended one.
        (
            [
                ("Minute as amended - 14 December 2023", "amended.pdf"),
                ("Minutes - 14 December 2023", "minutes.pdf"),
            ],
            "minutes.pdf",
        ),
        # A mayoral minute is never the minutes.
        ([("Mayoral Minute - 14 December 2023", "mayoral.pdf")], None),
    ],
)
def test_kiama_reads_the_singular_minute_as_amended(links, want_minutes):
    base = "https://www.kiama.nsw.gov.au/files/"
    html = "".join(f'<a href="{base}{href}">{text}</a>' for text, href in links)
    papers = KiamaScraper().papers(BeautifulSoup(html, "html.parser"))
    assert papers.get("minutes") == (base + want_minutes if want_minutes else None)
