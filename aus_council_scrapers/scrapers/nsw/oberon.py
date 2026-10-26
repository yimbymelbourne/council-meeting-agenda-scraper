"""Oberon Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2018 with a
year filter: Ordinary, Extraordinary, Works Committee and Finance Committee
meetings, plus "Other Meeting" rows.

Papers were one flat "Related Information" list until 2026, labelled by
their own text—"Ordinary Meeting Agenda and Business Papers - 17 December
2024", "Unconfirmed Minutes - 17 December 2024", or the filename
("241126-Agenda-and-Business-Papers-26-November-2024-Extraordinary-
Meeting.pdf"). The 20 October 2026 meeting files them under headings
instead ("Agenda & Business Paper", "Unconfirmed Minutes", each linked
"Download PDF"). ``papers_by = "heading"`` reads both: a payload with no
headings is read by link text.

Every paper's filename starts with its meeting's date as yymmdd
("241217-ordinary-meeting-agenda-..."), and twice a payload carries
another meeting's paper under that other meeting's date: the 7 June 2022
Works Committee lists the 21 June 2022 Ordinary agenda
("220621-Agenda-and-Business-Papers-21-June-2022-Ordinary-Meeting.pdf"),
and the 16 March 2021 Ordinary meeting the 30 March 2021 Works Committee
minutes ("210330-Confirmed-Minutes-Works-Committee-March-2021.pdf"), which
would outrank its own unconfirmed minutes. A paper whose filename opens
with the date of another meeting on the listing is that meeting's, so it is
passed over (`build_return`). A prefix naming no listed meeting is kept: the
21 May 2024 agenda is "240517-agenda-business-paper-...-21-may-2024.pdf".

Two more labels the base class cannot read, fixed in `papers`: the 16
April 2024 minutes are "Confirmed Mintues - 16 April 2024", and four 2023
agendas are labelled only with the meeting:

- "230221_Ordinary_Meeting_21_Feb_2023.pdf" (21 February)
- "230307-Works-Committee-Meeting-7-March-2023-1.pdf" (7 March)
- "230321_Ordinary_Meeting_21_Mar_2023-Inline.pdf" (21 March)
- "Oberon-Council-Ordinary-Meeting-18-April-2023.pdf" (18 April)

Each sits beside files named as the minutes or a late report, or alone.
All four PDFs open with the meeting's cover page ("Oberon Council Ordinary
Meeting ... Commencing at 5:30 pm"; "Works Committee Meeting ...
Commencing at 2:00 pm") and are the business paper: 177-179 pages for
February and March, 435 for 18 April ("Oberon Council - Agenda - Ordinary
Meeting - 18 April 2023"), 47 for the Works Committee ("Oberon Council -
Agenda - Works Committee Meeting - 7 March 2023"), checked 26 Oct 2026.
Such a label is taken as the agenda only when nothing else is and the
payload has no headings.

The "Other Meeting" rows (seven in 2025-2026, checked 26 Oct 2026) carry a
YouTube recording and at most a presentation or Q&A responses, never an
agenda or minutes, so `meeting_types` leaves them out before their payload
is fetched.

One production year is the listing filtered to that year (``page_size``
makes it one page) and a payload per meeting: 11 requests for 2026.
"""

import datetime
import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _SIZE_SUFFIX,
)

# A documented robots.txt exception. www.oberon.nsw.gov.au/robots.txt has
# `Disallow: /Council/*` for `User-agent: *` (checked 26 Oct 2026), and the
# only meetings listing is /Council/Council-Meetings, so every listing request
# (`?dlv_OC CL Public Meetings=...`) is under it. The maintainer decided on
# 26 Oct 2026 to read it anyway, as for `swan`, because these papers are the
# council's official public record. Nothing else on the host is disallowed
# for what this reads: the document payloads (/OCServiceHandler.axd) and the
# papers (/files/assets/...) are allowed. robots.txt sets no Crawl-delay.

# "Confirmed Mintues - 16 April 2024".
_MINUTES_TYPO = re.compile(r"\bmintues\b", re.IGNORECASE)

# "230221_Ordinary_Meeting_21_Feb_2023.pdf",
# "230307-Works-Committee-Meeting-7-March-2023-1.pdf",
# "230321_Ordinary_Meeting_21_Mar_2023-Inline.pdf",
# "Oberon-Council-Ordinary-Meeting-18-April-2023.pdf": the business paper,
# labelled with nothing but the meeting. The whole label must be that, so a
# name carrying a paper type ("...-Confirmed-Minutes_1.pdf", "Late_Report")
# never matches. Whitespace is read as "_".
_TITLE_ONLY_AGENDA = re.compile(
    r"^(?:\d{6}[-_])?(?:Oberon[-_]Council[-_])?"
    r"(?:Ordinary|Extraordinary|(?:Works|Finance)[-_]Committee)[-_]Meeting[-_]"
    r"\d{1,2}[-_][A-Za-z]{3,9}[-_]\d{4}(?:-Inline|-\d)?\.pdf$",
    re.IGNORECASE,
)

# "220621-Agenda-...", "210330_works_committee_...": the meeting's date as
# yymmdd at the start of the filename.
_DATE_PREFIX = re.compile(r"^(\d{2})(\d{2})(\d{2})(?!\d)")


def _prefix_date(href: str) -> datetime.date | None:
    name = unquote(urlparse(href).path.rsplit("/", 1)[-1])
    m = _DATE_PREFIX.match(name)
    if not m:
        return None
    try:
        return datetime.date(2000 + int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


@register_scraper
class OberonScraper(OpenCitiesMeetingsScraper):
    # One production year (`--years 2026`, 11 requests) took 23.5 s from a
    # home connection on 26 Oct 2026. Orders dispatch only (slowest first);
    # see BaseScraper.expected_seconds.
    expected_seconds = 24

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    meeting_types = re.compile(r"\b(?:Ordinary|Extraordinary|Committee)\b")
    # The busiest year since 2020 is 20 meetings: one listing page a year.
    page_size = 50

    def __init__(self):
        super().__init__(
            "oberon",
            "NSW",
            "https://www.oberon.nsw.gov.au/Council/Council-Meetings",
        )

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        meeting = parse_date(row.date, dayfirst=True).date()
        listed = getattr(self, "_listed_dates", set())
        for anchor in content.find_all("a", href=True):
            day = _prefix_date(anchor["href"])
            if day and day != meeting and day in listed:
                self.logger.info(
                    f"{row.date} {row.meeting_type}: passing over "
                    f"{anchor['href'].rsplit('/', 1)[-1]!r}, the {day} meeting's"
                )
                anchor.decompose()
        return super().build_return(content, row)

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        for anchor in content.find_all("a", href=True):
            for text in anchor.find_all(string=_MINUTES_TYPO):
                text.replace_with(_MINUTES_TYPO.sub("Minutes", text))
        papers = super().papers(content)
        if papers.get("agenda") or content.find("div", class_="meeting-document"):
            return papers
        for anchor in content.find_all("a", href=True):
            label = _SIZE_SUFFIX.sub("", anchor.get_text(" ", strip=True)).strip()
            if _TITLE_ONLY_AGENDA.match(re.sub(r"\s+", "_", label)):
                papers["agenda"] = urljoin(self.base_url, anchor["href"])
                break
        return papers
