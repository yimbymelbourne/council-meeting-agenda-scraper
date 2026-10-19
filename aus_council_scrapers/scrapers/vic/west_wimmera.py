"""West Wimmera Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing is "Minutes and Agenda" (``OC CL Public Meetings``), a child of
the Council Meetings landing page. The year filter offers 2016–2026; 2020
onwards is fetched.

Papers sit in ``div.meeting-document`` sections, but only since 2024 are
their headings the plain "Agenda" and "Minutes" the base class's heading
mode expects. Before that the heading is free text, and the paper's name is
rarely first:

* "21 December 2022 - Council Meeting Agenda", "19th April 2023 Council
  Meeting Agenda", "Unscheduled Council Meeting Agenda - 2nd Oct 2023"
* "Council Meeting Minutes - Confirmed", "17 Feb 2021 Confirmed Council
  Meeting Minutes", "Special Meeting Minutes 19 Aug 20"
* beside them "Attachments - Item 12", "Agenda Attachment Items 9.1 - 14.1",
  "Late Item Report", "Council Meeting Recording", "Community Forum Record"

Read with heading mode, 43 of the 107 meetings since 2020 came back with no
papers at all. So `papers` classifies a heading by the words anywhere in it:
minutes if it says minutes, else agenda if it says agenda, passing over
attachments, late items, recordings and records. One heading names neither—
"2 November 2022 - Statutory Council Meeting to elect the Mayor"—and its
file ("2022-11-02-statutory-meeting-agenda-to-elect-mayor.pdf") is the
agenda, so a heading naming no paper is classified by its filename, ranked
below any heading that does. In December 2022 the item attachments are
sections nested inside the agenda's section; only top-level sections are
papers.

Since about 2025 the agenda and minutes are published "with attachments",
one file of up to ~200 MB each; they are still the agenda and the minutes.
On 16 May 2025 the same file is offered under both headings, and is kept as
the agenda only (see `_papers`).

Types are "Council meeting" and "Special council meeting". Rows before
September 2020 have a blank type; their payloads open "Council Meeting" or
"Special Council Meeting - August 19, 2020", which names them. 19 August
2020 is two rows, a Council meeting and a Special meeting, and stays two
records. Unscheduled meetings (nine since 2023) and the statutory meetings
of 3 November 2021 and 5 November 2025 are typed "Council meeting", and are
named from their filenames instead: "unscheduled-council-meeting-agenda-…",
"2021-11-03-statutory-meeting-agenda-to-elect-mayor.pdf". One production year is one listing page (pagesize=100) plus one
payload per meeting: 11 requests for 2026.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _AGENDA,
    _MINUTES,
    _NOT_THE_PAPER,
    _ONE_ITEM,
    _is_minutes_file,
    _is_pdf,
    _label,
    _papers,
    _pick,
)
from aus_council_scrapers.scrapers.vic._paper_kind import KIND, paper_kind

# Sections beside the papers that are neither: the livestream recording (a
# PDF holding a link, on 15 December 2021) and the community forum record.
_NOT_A_PAPER = re.compile(r"\brecord(?:ing)?\b", re.IGNORECASE)

_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


def _own_pdf(section, base_url: str) -> str | None:
    """The section's first PDF that is not inside a section nested in it."""
    for anchor in section.find_all("a", href=True):
        href = anchor["href"].strip()
        if not _is_pdf(href):
            continue
        if anchor.find_parent("div", class_="meeting-document") is not section:
            continue
        if anchor.find_parent("div", class_="meeting-attachments"):
            continue
        return urljoin(base_url, href)
    return None


@register_scraper
class WestWimmeraScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 21 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 21

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    # The year-filtered page carries the full year dropdown (checked 20 Oct
    # 2026), so production reads its one year without the bare page first.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "west_wimmera",
            "VIC",
            "https://www.westwimmera.vic.gov.au/Council/Inside-council"
            "/Council-Meetings/Minutes-and-Agenda",
        )
        self.default_name = "Council meeting"

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        sections = [
            section
            for section in content.find_all("div", class_="meeting-document")
            if section.find_parent("div", class_="meeting-document") is None
        ]
        if not sections:
            return super().papers(content)

        agendas: list[tuple[str, str, int]] = []
        minutes: list[tuple[str, str, int]] = []
        for section in sections:
            h3 = section.find("h3")
            heading = _label(h3.get_text(" ", strip=True)) if h3 else ""
            if (
                not heading
                or _NOT_THE_PAPER.search(heading)
                or _ONE_ITEM.search(heading)
                or _NOT_A_PAPER.search(heading)
            ):
                continue
            url = _own_pdf(section, self.base_url)
            if not url:
                continue
            if _MINUTES.search(heading):
                minutes.append((heading, url, 0))
            elif _AGENDA.search(heading):
                if not _is_minutes_file(url):
                    agendas.append((heading, url, 0))
            else:
                filename = _label(
                    urlparse(url).path.rsplit("/", 1)[-1].replace("-", " ")
                )
                if _NOT_THE_PAPER.search(filename):
                    continue
                if _is_minutes_file(url):
                    minutes.append((heading, url, 1))
                elif _AGENDA.search(filename):
                    agendas.append((heading, url, 1))
        return _papers(_pick(agendas), _pick(minutes))

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        name = row.meeting_type
        if not name:
            opening = content.find("p")
            if opening and _SPECIAL.search(opening.get_text(" ", strip=True)):
                return "Special council meeting"
            name = self.default_name
        if KIND.search(name):
            return name
        # Unscheduled and statutory meetings are typed "Council meeting"; the
        # files say which they were (see `_paper_kind`).
        kind = paper_kind(papers.get("agenda"), papers.get("minutes"))
        return f"{kind} council meeting" if kind else name
