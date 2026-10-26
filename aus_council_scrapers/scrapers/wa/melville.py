import datetime
import re
import urllib.parse

from aus_council_scrapers.alyka import (
    KsearchScraper,
    filename_of,
    find_date,
)
from aus_council_scrapers.base import ScraperReturn, register_scraper

_BASE_URL = "https://www.melvillecity.com.au"
_LISTING_URL = f"{_BASE_URL}/our-city/our-council/agendas-and-minutes"

# Melville's ksearch returns every document it has published since 2010 in one
# response, one record per *document*: "Agenda - Ordinary Meeting of Council -
# 20 October 2026", "DAU - Minutes - 27 July 2026". The title carries the
# meeting's exact date.
#
# What the listing does not carry is the agenda of a meeting that already has
# minutes. Each council meeting is one page on the site, and the listing shows
# only that page's first file—the agenda until the minutes go up, the
# minutes from then on. Records flagged `MoreInfo` have more files than that,
# and the agenda is among them, so reading it means fetching the page: one
# request per meeting. The agenda has to be there—a meeting's papers are the
# point—so the cost is bounded instead, by meeting type:
#
#   Ordinary and Special Meetings of Council—where decisions are made
#   Development Advisory Unit—the city's development assessment panel; its
#     agendas and minutes are separate single-file records, so they cost
#     nothing extra
#   Audit Risk & Improvement Committee and the two electors' meetings—
#     about five a year between them, each a page fetch for its agenda
#
# Left out: the Agenda Briefing Forum. It is a pre-meeting briefing, not a
# decision-making meeting, its "notes" are not minutes, and with nine or ten a
# year it would add as many page fetches—about 20 s more at the per-host
# delay. A production year is then about seventeen requests rather than
# forty.
_MEETING_TYPES = {
    "ordinary meeting of the council": "Ordinary Meeting of Council",
    "special meeting of the council": "Special Meeting of Council",
    "development advisory unit": "Development Advisory Unit",
    "audit risk & improvement committee": "Audit, Risk and Improvement Committee",
    "special meeting of electors": "Special Meeting of Electors",
    "annual general meeting of electors": "Annual General Meeting of Electors",
}

# Meetings the council's own listing misdates, keyed by the file it links.
# Both the title ("DAU – Agenda – 26 February 2026") and the filename
# ("...-Friday-27-February-2026.pdf") are wrong; the agenda's first page
# calls the meeting for Monday 23 February 2026, the date its minutes carry.
_DATE_CORRECTIONS = {
    "Development-Advisory-Unit-Agenda-Friday-27-February-2026.pdf": (
        datetime.date(2026, 2, 23)
    ),
}

_MINUTES = re.compile(r"\bminutes?\b", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_DAU = re.compile(r"^\s*DAU\b", re.IGNORECASE)
# Two DAU sessions on one day are listed as "(Item 1)" and "(Item 2)", each
# with its own agenda and minutes.
_ITEM = re.compile(r"\(\s*item\s*(\d+)\s*\)", re.IGNORECASE)
# On a meeting page, the meeting's own papers are labelled "Agenda - ..." and
# "Minutes - ..."; written submissions, late items, presentations and the
# numbered report attachments sit alongside them.
_PAGE_AGENDA = re.compile(r"^\s*agenda\b", re.IGNORECASE)
_PAGE_MINUTES = re.compile(r"^\s*(?:confirmed\s+)?minutes\b", re.IGNORECASE)


def _document_kind(title: str):
    """Whether a listing record is a meeting's agenda, its minutes, or neither.

    Audio notices, "Late Item ..." reports and briefing notes are neither. A
    DAU record titled only "DAU - <date>"—the form used until 2025—is the
    unit's reports and recommendations for that sitting, which is its agenda.
    """
    if _MINUTES.search(title):
        return "minutes"
    if _AGENDA.search(title):
        return "agenda"
    if _DAU.match(title):
        return "agenda"
    return None


@register_scraper
class MelvilleScraper(KsearchScraper):
    listing_url = _LISTING_URL

    # One production year, measured 19 Oct 2026 from a home IP: 33 s (about 18
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 33

    def __init__(self):
        super().__init__("melville", "WA", _BASE_URL)

    def _page_documents(self, page_url: str) -> dict:
        """The agenda and minutes linked from one meeting's page."""
        soup = self._page(page_url)
        # Each file sits in its own `.minutesagendas-table`; the page chrome
        # around them links unrelated notices from the same asset store.
        found = {}
        for link in soup.select(".minutesagendas-table a[href]"):
            if "getContentAsset" not in link["href"]:
                continue
            label = link.get_text(" ", strip=True)
            url = urllib.parse.urljoin(_BASE_URL, link["href"])
            if _PAGE_MINUTES.match(label):
                found.setdefault("minutes", url)
            elif _PAGE_AGENDA.match(label):
                found.setdefault("agenda", url)
        return found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        endpoint, search_param = self._ksearch_config(self._listing_page())
        records = self._ksearch(endpoint, search_param, [])
        wanted = self._wanted_years()

        meetings: dict[tuple, dict] = {}
        for record in records:
            name = _MEETING_TYPES.get((record.get("MNAMeetingType") or "").lower())
            if not name:
                continue
            title = re.sub(r"\s+", " ", record.get("ArticleTitle") or "").strip()
            found = find_date(title)
            first_file = record.get("MNAFirstFileUrl")
            date = _DATE_CORRECTIONS.get(filename_of(first_file or "")) or (
                found[0] if found else None
            )
            if not date or date.year not in wanted:
                continue
            item = _ITEM.search(title)
            key = (name, date, item.group(1) if item else None)
            meeting = meetings.setdefault(
                key, {"page": None, "listed": {}, "webpage": None}
            )

            page_url = record.get("PageUrl")
            if page_url:
                meeting["webpage"] = meeting["webpage"] or urllib.parse.urljoin(
                    _BASE_URL, page_url
                )
            if record.get("MoreInfo") and page_url:
                meeting["page"] = urllib.parse.urljoin(_BASE_URL, page_url)

            kind = _document_kind(title)
            if kind and first_file:
                meeting["listed"].setdefault(
                    kind, urllib.parse.urljoin(_BASE_URL, first_file)
                )

        results = []
        for (name, date, _), meeting in sorted(
            meetings.items(), key=lambda m: m[0][1], reverse=True
        ):
            documents = {}
            if meeting["page"]:
                try:
                    documents = self._page_documents(meeting["page"])
                except Exception as e:
                    # The listing's own file is still worth keeping.
                    self.logger.warning(f"Could not read {meeting['page']}: {e}")
            for kind, url in meeting["listed"].items():
                documents.setdefault(kind, url)

            result = self._meeting(
                name=name,
                date=date,
                webpage_url=meeting["webpage"] or _LISTING_URL,
                agenda_url=documents.get("agenda"),
                minutes_url=documents.get("minutes"),
            )
            if result:
                results.append(result)

        self._log_result(results, f"{len(records)} listed documents")
        return results
