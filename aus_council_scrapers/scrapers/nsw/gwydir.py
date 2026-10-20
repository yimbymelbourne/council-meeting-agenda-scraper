import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesArchive,
    papers_by_link_text,
)
from aus_council_scrapers.resolve import ResolveScraper

# The council's OpenCities meetings listing, which holds its papers from 2018
# to August 2026.
MEETINGS = "https://www.gwydir.nsw.gov.au/Council/Council-Meetings"


@register_scraper
class GwydirScraper(ResolveScraper):
    # One production year, measured 20 Oct 2026 from a home IP, alone: 18 s,
    # most of it the eight OpenCities payloads at the site's 2 s spacing.
    # Orders dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 18

    # Gwydir moved to Resolve for its 24 September 2026 Ordinary Meeting, the
    # tenant's first event; the OpenCities listing's newest row is 27 August
    # 2026. So 2026 needs both: the listing for January to August, the
    # tenant from September on. From 2027 a production year is the tenant
    # alone and the listing costs nothing.
    tenant = "gwydir"
    resolve_from = datetime.date(2026, 9, 24)

    # Every event the tenant has is an Ordinary Council meeting; the pattern
    # names Extraordinary too, so a committee the council starts publishing
    # there cannot add a request per meeting to the nightly run unasked.
    meeting_types = re.compile(r"^(Ordinary|Extraordinary|Special) Council$")
    # Named as the archive's are named below, so a meeting type reads the
    # same either side of the move.
    meeting_type_names = {
        "Ordinary Council": "Ordinary Council Meeting",
        "Extraordinary Council": "Extraordinary Council Meeting",
        "Special Council": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("gwydir", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        before = self.before_resolve(wanted)
        if not before:
            return []
        return _Archive(
            self, MEETINGS, _archive_name, meeting_types=_ARCHIVE_TYPES
        ).read(set(before), before=self.resolve_from)


class _Archive(OpenCitiesArchive):
    """Gwydir's listing, read in heading mode, with two gaps filled.

    Heading mode is right for every payload but two, and search mode, which
    would fill both, takes "ARIC Minutes" (the audit committee's, filed on
    30 May 2024) for the meeting's own. So the gaps are filled here, only
    where heading mode found nothing.
    """

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        # The audit committee's minutes ride along on some Council meetings:
        # "ARIC-Minutes.pdf" listed before the meeting's own "Minutes No
        # Attachments.pdf" on 7 August 2024, which link-text mode would take.
        # An ARIC paper is never the Council meeting's.
        # And the meeting's own minutes are "Minutes No Attachments.pdf",
        # which reads as an attachment until the qualifier is taken off.
        for anchor in content.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            if _ARIC.search(text):
                anchor.decompose()
            elif _NO_ATTACHMENTS.search(text):
                anchor.string = _NO_ATTACHMENTS.sub("", text)
        papers = super().papers(content)
        if "minutes" not in papers:
            # 30 October 2025 heads its minutes "Ordinary Meeting Minutes -
            # 30 October 2025", which heading mode's leading-name rule does
            # not take off, since it wants a dash after "Meeting".
            for section in content.find_all("div", class_="meeting-document"):
                heading = section.find("h3")
                link = section.find("a", href=True)
                if (
                    heading
                    and link
                    and _COUNCIL_MINUTES.match(heading.get_text(" ", strip=True))
                    and link["href"].lower().endswith(".pdf")
                ):
                    papers["minutes"] = urljoin(self.base_url, link["href"])
                    break
        if "agenda" not in papers:
            # 26 February 2026 has a "Minutes" section and its agenda only in
            # the Related Information list, as "Agenda Ordinary Council
            # Meeting 26 February 2026".
            related = content.find_all("div", class_="meeting-attachments")
            if related:
                listed = papers_by_link_text(
                    BeautifulSoup("".join(str(div) for div in related), "html.parser"),
                    self.base_url,
                )
                if "agenda" in listed and listed["agenda"] != papers.get("minutes"):
                    papers["agenda"] = listed["agenda"]
        return papers

    def build_return(self, content: BeautifulSoup, row: ListingRow):
        record = super().build_return(content, row)
        wrong = _WRONG_PAPERS.get(row.cvid)
        if record and wrong:
            setattr(record, f"{wrong}_url", None)
            record.download_url = record.agenda_url or record.minutes_url
        return record


_ARIC = re.compile(r"\bARIC\b")
_NO_ATTACHMENTS = re.compile(r"\s*\bno\s+attachments\b", re.IGNORECASE)

# Papers the listing files against the wrong meeting, by the row's cvid. The
# 14 July 2022 Community Services and Planning Committee links, as its
# minutes, the committee's 8 July 2021 minutes: the same file that meeting
# links (".../july-2021/community-service-planning-minutes.pdf").
_WRONG_PAPERS = {"0102535a-5329-48e1-b196-5df63e7ae367": "minutes"}

_COUNCIL_MINUTES = re.compile(
    r"^(?:ordinary|extraordinary|special)\s+meeting\s+minutes\b", re.IGNORECASE
)


# Council meetings, and the Community Services and Planning Committee: all
# the councillors, with planning in its remit. Its last meeting on the
# listing is 7 November 2024. Left out is the Public Infrastructure
# Committee (roads, water and works); each kept meeting costs a payload
# request. The 2026 listing holds Council meetings only.
_ARCHIVE_TYPES = re.compile(
    r"^(Ordinary|Extraordinary|Special) Meeting$|^Community Service and Planning"
)


def _archive_name(meeting_type: str, title: str) -> str:
    # The listing types its Council rows "Ordinary Meeting", "Extraordinary
    # Meeting" and "Special Meeting"; the tenant's form of the name is used
    # for those, and a committee keeps its own.
    match = re.match(r"^(Ordinary|Extraordinary|Special) Meeting$", meeting_type)
    if match:
        return f"{match.group(1)} Council Meeting"
    return meeting_type
