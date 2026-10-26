"""Upper Hunter Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

Upper Hunter splits its meetings into two lists, like Kingston:

* **Past meetings**, ``OC CL Public Past Meetings``, at
  ``.../Past-Meetings-minutes-and-agendas``. The name was checked against
  the ``dlv_`` year filter: the 2023 filter returns only 2023 rows, while
  ``OC CL Public Meetings`` is ignored and serves the unfiltered list.
* **Upcoming meetings**, ``OC CL Public Upcoming Meetings``, on the parent
  page. Its name was checked the same way (October 2026): asking it for
  2027 returns no rows, where three wrong names each return the nine
  upcoming rows unfiltered. A meeting is listed here before its papers
  are: on 20 October 2026 the 26 October and 30 November Ordinary Council
  Meetings were both here with no papers yet, so both were skipped. The
  list is read so that an agenda posted while its meeting is still
  upcoming is picked up the night it appears.

Both lists mix the Council's meetings with its three standing committees
(Corporate Services, Infrastructure Services, Environmental & Community
Services) and the town Community Advisory Committees: about 50 rows a year,
of which 10 to 14 are Council meetings. Each listed meeting costs a payload
request, so ``meeting_types`` keeps the Ordinary and Extraordinary Council
Meetings, which brings a production year from about 50 requests to about 15.

The payload layout changed in mid-2023. Up to 31 July 2023 papers are
filed under headings ("Agenda", "Minutes", "Draft Minutes"), each paper a
"Download PDF" link, with the agenda's attachments listed again under the
same heading. From then on they are one flat "Related Information" list
labelled by link text ("Agenda", "Excluded Attachments", "Late Report",
"Minutes"). ``papers_by = "heading"`` covers both: heading mode reads a
payload that has no headings by its link text. Two labels need help, in
`papers`, and three need more:

* The 19 December 2022 minutes are headed "Council Minutes - 19 December
  2022", with the body named first.
* The 6 May 2024 Extraordinary meeting's minutes link reads "Mintues".
* In February to April 2023 the "Agenda" heading holds no paper of its own,
  only a nested Related Information list whose first entry is the agenda,
  labelled "Business Paper" or "Business Papers" (27 February, 27 March and
  24 April 2023), beside late reports and the draft plans on exhibition.
  Heading mode ignores nested lists, because elsewhere they link other
  meetings' papers, so the "Business Paper" link is taken from that list
  when the heading has nothing else.

Six Council meetings carry an agenda and no minutes (27 November 2023, 17
and 28 April 2025, 26 May 2025, 25 May and 27 July 2026, checked October
2026): the payload holds no minutes file.

The past list's year filter offers 2018 and 2021–2026. 2021 holds only two
meetings (25 October and 29 November 2021); there is nothing for 2019 or
2020.

``page_size`` and ``year_filtered_first_page`` were checked (October 2026):
a ``(pagesize=100)`` page holds all 63 of 2025's rows, and the filtered
page carries the full year dropdown. So a production year is one past-list
request, one upcoming-list request and one payload per Council meeting.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    Listing,
    ListingRow,
    OpenCitiesMeetingsScraper,
)

_MEETINGS = (
    "https://www.upperhunter.nsw.gov.au/Council/Council-and-Committee-Meetings/"
    "Council-and-Committee-Meetings"
)

# "Council Minutes - 19 December 2022": the body named before the paper.
# Heading mode anchors "Minutes" at the start, so the prefix is dropped.
_COUNCIL_PREFIX = re.compile(r"^\s*council\s+(?=minutes\b)", re.IGNORECASE)

# The 6 May 2024 Extraordinary Council Meeting's minutes link reads "Mintues
# (PDF, 185KB)".
_MINUTES_TYPO = re.compile(r"\bmintues\b", re.IGNORECASE)

# The agenda's label inside the 2023 "Agenda" sections' nested lists.
_BUSINESS_PAPER = re.compile(r"^business\s+papers?\b", re.IGNORECASE)
_AGENDA_HEADING = re.compile(r"^agenda$", re.IGNORECASE)


@register_scraper
class UpperHunterScraper(OpenCitiesMeetingsScraper):
    # One production year (2026), measured 20 Oct 2026 from a home IP: 13
    # requests (the past and upcoming listing pages and 11 payloads), 26 s.
    # Orders dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 26

    list_name = "OC CL Public Past Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = re.compile(
        r"^(?:ordinary|extraordinary) council meeting$", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "upper_hunter",
            "NSW",
            f"{_MEETINGS}/Past-Meetings-minutes-and-agendas",
        )

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [Listing(_MEETINGS, "OC CL Public Upcoming Meetings")]

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            fixed = _COUNCIL_PREFIX.sub("", text, count=1)
            if fixed != text:
                heading.string = fixed
        for anchor in content.find_all("a", href=True):
            text = anchor.get_text(" ", strip=True)
            if _MINUTES_TYPO.search(text):
                anchor.string = _MINUTES_TYPO.sub("Minutes", text)
        papers = super().papers(content)
        if "agenda" not in papers:
            agenda = self._business_paper(content)
            if agenda and agenda != papers.get("minutes"):
                papers["agenda"] = agenda
        return papers

    def _business_paper(self, content: BeautifulSoup) -> str | None:
        """The "Business Paper" PDF nested under an "Agenda" heading."""
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            if not h3 or not _AGENDA_HEADING.match(h3.get_text(" ", strip=True)):
                continue
            for anchor in section.find_all("a", href=True):
                href = anchor["href"].strip()
                label = anchor.get_text(" ", strip=True)
                if href.lower().endswith(".pdf") and _BUSINESS_PAPER.match(label):
                    return urljoin(self.base_url, href)
        return None

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        # The payload's time is "12:00 AM" on twelve meetings (2022 and 2024):
        # a time left unset, not a midnight meeting. Reporting it would claim a
        # time nobody published, so the record carries none, as gosnells does.
        if record is not None and record.time == "12:00 AM":
            record.time = None
        return record
