"""City of Monash—OpenCities, on `OpenCitiesMeetingsScraper`.

Replaces an empty placeholder stub.

One list (``OC CL Public Meetings``), starting at 28 September 2021—the
year filter offers nothing earlier. Paging inside a filtered year is a plain
GET (``(pageindex=N)``), verified on 2025's two pages.

**There is no agenda PDF for most meetings.** Monash files its papers in two
folders (``div.meeting-folder`` titled "Agenda" and "Minutes"), and for a
Council meeting the Agenda folder holds one PDF per agenda item—"7.1.1 Town
Planning Schedule", "7.1.2 TPA/57779 - 1816-1832 Dandenong Rd, Clayton",
twenty-odd of them—with no combined agenda. Taking any one of those as the
agenda would store an item report as the meeting's agenda. What the council
offers as the agenda is the meeting's own page, linked from the payload as
"View this agenda in a new window": the item list with each report linked. So
that page is the record's ``agenda_html_url``.

**What production does with that.** council-alerts' ``ingestCouncils.ts``
creates an agenda document only when ``agenda_url`` is set—``agenda_html_url``
rides along on that document and is never ingested alone—and it drops a
meeting with no ``agenda_url``, ``download_url`` or ``minutes_url`` entirely.
So for an ordinary Monash meeting, production sees nothing until the minutes
are up, and then sees minutes only. That is a gap in what Monash publishes
(no agenda PDF exists to give it), not in this scraper; closing it means
council-alerts ingesting ``agenda_html_url`` on its own.

``agenda_url`` is set when the Agenda folder holds exactly one paper that is
the whole agenda: a title saying agenda or notice paper, or naming the
meeting—"Committee of Council Meeting Agenda - 12 December 2023", "Full
meeting agenda" (12 November 2024), "Notice Paper" (9 November 2021 and,
beside its two item papers, 19 October 2021), "2023 Committee Meeting of
Council - Annual Budget" (5 December 2023)—or a filename saying agenda, which
is the only label on 6 December 2022's "Project Bids for Draft Budget
2023/24" (``...-budget-submissions-meeting-agenda.pdf``). Item-numbered
titles never count. Checked against every Agenda folder recorded in October
2026, 1,380 papers in all: the test picks exactly one paper in seven folders
and nothing else. The first page of each of those seven is the agenda.
The 13 October 2026 Additional Meeting's Agenda folder holds one numbered
item ("4.1.1 2025-26 Financial and Performance Statements") and links a
public notice rather than an agenda page, so it gets minutes only. The 20
August 2024 confidential meeting published only a confidentiality
certificate and no minutes, and is skipped.

The Minutes folder holds the one minutes PDF ("Council Meeting 29 September
2026 - Unconfirmed Minutes", "Meeting Minutes").

Every row's meeting type is "Meeting". The payload's opening sentence says
which kind—"Agenda of the Meeting of Monash Council", "Agenda of the
Committee Meeting of Council", "Additional Meeting of Monash City
Council"—so the name comes from that.

All meetings are Council meetings, about 14 a year, so nothing is allowlisted.
One production year is the unfiltered page, one or two filtered pages and one
payload per meeting: 12 requests and 22 s for 2026, measured in October 2026.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
    _pick,
)

# An agenda item's own paper: "7.1.1 Town Planning Schedule", "13.2 SRL
# Update - Confidentiality Certificate", "1.2. 530-540 Springvale Road".
_ITEM_NUMBER = re.compile(r"^\d+(?:\.\d+)+\.?\s")
# A paper is the whole agenda only when it says so, in its title or its
# filename. Single-paper Agenda folders also hold "Glen Waverley Parking -
# Confidentiality Certificate." (20 August 2024), which is what that meeting
# considered, not its agenda.
_WHOLE_AGENDA = re.compile(
    r"\bagenda\b|\bnotice\s+paper\b|\b(?:council|committee)\s+meeting\b"
    r"|\bmeeting\s+of\s+(?:monash\s+(?:city\s+)?)?council\b",
    re.IGNORECASE,
)
_AGENDA_FILE = re.compile(r"\bagenda\b|\bnotice\s+paper\b", re.IGNORECASE)
_AGENDA_PAGE = re.compile(r"\bview\s+this\s+agenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)


def _folder_papers(folder, base_url: str) -> list[tuple[str, str]]:
    papers = []
    for document in folder.find_all("div", class_="meeting-document"):
        anchor = next(
            (a for a in document.find_all("a", href=True) if _is_pdf(a["href"])),
            None,
        )
        if anchor is None:
            continue
        title = document.find(class_="meeting-document-title")
        label = _label(title.get_text(" ", strip=True) if title else "")
        papers.append((label, urljoin(base_url, anchor["href"].strip())))
    return papers


def _is_whole_agenda(label: str, url: str) -> bool:
    if _ITEM_NUMBER.match(label):
        return False
    filename = _label(urlparse(url).path.rsplit("/", 1)[-1].replace("-", " "))
    return bool(_WHOLE_AGENDA.search(label) or _AGENDA_FILE.search(filename))


@register_scraper
class MonashScraper(OpenCitiesMeetingsScraper):
    list_name = "OC CL Public Meetings"

    def __init__(self):
        super().__init__(
            "monash",
            "VIC",
            "https://www.monash.vic.gov.au/About-Us/Council/Council-Meetings/Agendas-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers: dict[str, str] = {}
        for folder in content.find_all("div", class_="meeting-folder"):
            title = folder.find("h3")
            heading = _label(title.get_text(" ", strip=True)) if title else ""
            documents = _folder_papers(folder, self.base_url)
            if re.match(r"^agenda\b", heading, re.IGNORECASE):
                whole = [
                    url for label, url in documents if _is_whole_agenda(label, url)
                ]
                if len(whole) == 1:
                    papers["agenda"] = whole[0]
            elif re.match(r"^minutes\b", heading, re.IGNORECASE):
                named = [
                    (label, url, 0)
                    for label, url in documents
                    if _MINUTES.search(label)
                ]
                chosen = _pick(named) or (
                    documents[0][1] if len(documents) == 1 else None
                )
                if chosen:
                    papers["minutes"] = chosen

        page = content.find("a", href=True, string=_AGENDA_PAGE)
        if page is not None:
            papers["agenda_html"] = urljoin(self.base_url, page["href"].strip())
        return papers

    def meeting_name(self, row: ListingRow, content: BeautifulSoup) -> str:
        intro = content.find("p")
        text = intro.get_text(" ", strip=True) if intro else ""
        if re.search(r"\bcommittee\s+meeting\s+of\s+council\b", text, re.IGNORECASE):
            return "Committee Meeting of Council"
        if re.search(r"\badditional\b", text, re.IGNORECASE):
            return "Additional Council Meeting"
        if (
            re.search(r"\bspecial\b", text, re.IGNORECASE)
            or row.meeting_type == "Special"
        ):
            return "Special Council Meeting"
        return "Council Meeting"
