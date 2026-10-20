import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import OpenCitiesArchive
from aus_council_scrapers.resolve import ResolveScraper

# The council's OpenCities meetings listing, which holds every meeting from
# 2015 to February 2026 with its papers.
MEETINGS = "https://www.dungog.nsw.gov.au/Council/Meetings-Agendas-and-Minutes"


@register_scraper
class DungogScraper(ResolveScraper):
    # One production year, measured 20 Oct 2026 from a home IP, alone: 7.5
    # to 9.5 s for 14 requests, most of them the tenant's detail calls.
    # Orders dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 9

    # Dungog moved its business papers to Resolve for the 18 March 2026
    # Ordinary Meeting, the tenant's first event. The OpenCities listing
    # still lists every meeting after that too, but from March 2026 a row's
    # payload holds at most the agenda (18 March) or only the "Questions on
    # the Agenda" sheet (16 September); the agenda packet and the minutes
    # are on Resolve. So the listing is read for meetings before 18 March
    # 2026, and the tenant from that day on. A 2026 production run pays for
    # both: one listing page and a payload for the February meeting, beside
    # the tenant's listing and a detail call per meeting.
    tenant = "dungog"
    resolve_from = datetime.date(2026, 3, 18)

    # Ordinary and Extraordinary Council. Left out is the Public Forum, held
    # before some Ordinary meetings to hear residents, where nothing is
    # decided; each kept meeting costs a request to learn which documents it
    # has. Extraordinary meetings are typed "Ordinary Council" at times (8
    # April 2026) and are told apart by the event name; see `_SPECIAL` in
    # resolve.py.
    meeting_types = re.compile(r"^(Ordinary|Extraordinary) Council$")
    # Named as the OpenCities archive's are named below, so a meeting type
    # reads the same either side of the move.
    meeting_type_names = {
        "Ordinary Council": "Ordinary Council Meeting",
        "Extraordinary Council": "Extraordinary Council Meeting",
    }

    def __init__(self):
        super().__init__("dungog", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        before = self.before_resolve(wanted)
        if not before:
            return []
        # Every row is an Ordinary or Extraordinary meeting, so the listing
        # is not filtered by type. A year is one or two listing pages and a
        # payload request per meeting.
        return _Archive(self, MEETINGS, _archive_name).read(
            set(before), before=self.resolve_from
        )


class _Archive(OpenCitiesArchive):
    """Dungog's listing, whose payloads change layout over the years.

    Most payloads head each paper's section ("Agenda", "Meeting Agenda",
    "Extraordinary Minutes", "Agenda and Annexures"), but February 2021 and
    every 2022 meeting file them in folders instead (`<h3
    class="folder-title">Agenda</h3>`). Search mode reads both, and finds the
    word anywhere in the heading. Heading mode read neither "Meeting Agenda"
    (2020) nor the folders, and lost 2022 entirely.
    """

    papers_by = "search"

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers = super().papers(content)
        # The 24 June 2020 Extraordinary meeting's only agenda is the late
        # report, "co_20200624_agn_2105_sup_extra.pdf": InfoCouncil's SUP
        # code, a supplementary paper, which is not the agenda.
        agenda = papers.get("agenda", "")
        if _SUPPLEMENTARY.search(agenda.rsplit("/", 1)[-1]):
            del papers["agenda"]
        if "minutes" not in papers:
            minutes = _nested_minutes(content, self.base_url)
            if minutes:
                papers["minutes"] = minutes
        return papers


_SUPPLEMENTARY = re.compile(r"_sup(?:_|\.pdf$)", re.IGNORECASE)
_MINUTES_HEADING = re.compile(r"\bminutes\b", re.IGNORECASE)


def _nested_minutes(content: BeautifulSoup, base_url: str) -> Optional[str]:
    """The minutes where a minutes section holds them only in its nested
    Related Information list: the 26 June 2024 Extraordinary meeting's
    "Extraordinary Minutes" section lists two recordings and "Minutes (PDF,
    307KB)" there, and nothing else. Only a PDF whose file is named as
    minutes is taken."""
    for section in content.find_all("div", class_="meeting-document"):
        heading = section.find("h3")
        if not heading or not _MINUTES_HEADING.search(heading.get_text(" ")):
            continue
        for anchor in section.find_all("a", href=True):
            href = anchor["href"]
            name = urlparse(href).path.rsplit("/", 1)[-1]
            if name.lower().endswith(".pdf") and re.search(r"min", name, re.I):
                return urljoin(base_url, href)
    return None


def _archive_name(meeting_type: str, title: str) -> str:
    # The listing types its rows "Ordinary Meeting" and "Extraordinary
    # Meeting"; the tenant's names for the same two are used instead.
    if meeting_type.lower().startswith("extraordinary"):
        return "Extraordinary Council Meeting"
    return "Ordinary Council Meeting"
