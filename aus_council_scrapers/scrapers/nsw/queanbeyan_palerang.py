"""Queanbeyan-Palerang Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every Ordinary and Extraordinary
Council meeting and, until 2022, the Planning and Strategy meetings—a
committee of the whole council, kept because it is the planning body. It
reaches back to 2016; upcoming meetings appear once their agenda is up. All
three types are Council meetings, so nothing is allowlisted.

Papers are filed under headings with every link labelled "Download PDF", so
``papers_by = "heading"``. Two things about QPRC's headings defeat the base
class's start-anchored rules, and `papers` tidies them first:

* **The body comes first.** "Ordinary Minutes", "Ordinary Meeting Minutes",
  "Extraordinary minutes - 29 September 2021", "Planning and Strategy
  minutes", "Extraordinary Meeting Agenda" (11 November 2020). From 2023 to
  2025 every ordinary meeting's minutes are "Ordinary Minutes", so without
  this they carry no minutes at all. The body's name is stripped from the
  front of the heading.
* **Every meeting also has public forum minutes**, filed beside the
  meeting's own: "Minutes - Public Forum", "Public Forum Minutes", and once
  "Minutes - Public Form". The public forum is the session before the
  meeting where residents address councillors. Its minutes are not the
  meeting's, and "Minutes - Public Forum" is as plain a heading as "Minutes -
  Ordinary Meeting", so the base class would pick whichever is listed first.
  Those sections are dropped.

Supplementary agendas ("Supplementary Agenda - Item 10.5"), mayoral minutes
(singular) and the "attachments under separate cover" books in the Related
Information list are passed over by the base class. 8 February 2023 has only
an "Amended Agenda with updates to Item 9.1"—the original is in the Related
Information list—so an amended agenda is read as the agenda, ranked below a
plain one.

QPRC meets about twice a month, so one production year is a listing request
plus about 21 payloads: 22 requests for 2026, two over the usual aim, and
every one of them a Council meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

_BODY_FIRST = re.compile(
    r"^(?:ordinary|extraordinary|planning\s+and\s+strategy)(?:\s+meeting)?\s+"
    r"(?=(?:agenda|minutes)\b)",
    re.IGNORECASE,
)

# "Amended Agenda with updates to Item 9.1": "Item 9.1" would otherwise mark
# it as one item's paper. "amended" keeps it below a plain "Agenda".
_AMENDED_AGENDA = re.compile(r"^amended\s+agenda\b.*$", re.IGNORECASE)

# "Public Form" is the council's own typo (one meeting).
_PUBLIC_FORUM = re.compile(r"\bpublic\s+for(?:um|m)\b", re.IGNORECASE)


@register_scraper
class QueanbeyanPalerangScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 42–44 s for
    # 22 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 44

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "queanbeyan_palerang",
            "NSW",
            "https://www.qprc.nsw.gov.au/Council/Council-Business/Council-meetings",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        content = BeautifulSoup(str(content), "html.parser")
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            if not h3:
                continue
            heading = re.sub(r"\s+", " ", h3.get_text(" ", strip=True))
            if _PUBLIC_FORUM.search(heading):
                section.decompose()
                continue
            tidied = _BODY_FIRST.sub("", heading, count=1)
            tidied = _AMENDED_AGENDA.sub("Agenda - amended", tidied)
            if tidied != heading:
                h3.string = tidied
        return super().papers(content)
