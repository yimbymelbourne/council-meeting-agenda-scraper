import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.resolve import ResolveScraper

# One plain-HTML table per year. The www.sutherlandshire.nsw.gov.au copies
# of these pages and PDFs are behind a Cloudflare challenge; the cms host
# serves the same files without one.
SEAMLESS_YEAR = "https://cms.ssc.nsw.gov.au/DXP/Meetings-and-Minutes/{year}"


@register_scraper
class SutherlandShireScraper(ResolveScraper):
    # Sutherland publishes business papers through Resolve from its 22 June
    # 2026 meetings. Everything before that, from 2016 to 16 June 2026, is
    # on the council's Seamless CMS archive, read by `other_meetings`.
    #
    # The tenant also holds Council and Planning Standing Committee events
    # from February 2026, but its Local Planning Panel starts only on 7
    # July 2026, so the archive is the one source that has all three bodies
    # up to the move. Taking the archive for everything before 22 June, and
    # Resolve for everything after, also keeps the February to June events
    # from costing a detail call each.
    tenant = "sutherland"
    resolve_from = datetime.date(2026, 6, 22)

    # Council, the Planning Standing Committee (planning proposals,
    # strategic planning) and the Local Planning Panel, which determines
    # DAs. Left out are the corporate, community and infrastructure standing
    # committees, the Public Forum where residents address councillors, and
    # the Local Transport Forum. Each kept meeting costs a request to learn
    # which documents it has, and the tenant lists about 90 events a year.
    meeting_types = re.compile(
        r"^(Council|Planning Standing Committee"
        r"|Sutherland Shire Local Planning Panel)$"
    )
    # The type is named "Council"; the meetings are "Council Meeting".
    meeting_type_names = {"Council": "Council Meeting"}

    def __init__(self):
        super().__init__("sutherland", "NSW")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        # One request a year, documents and all, so the archive is cheap:
        # production's current year costs one extra request.
        results = []
        for year in self.before_resolve(wanted):
            if year < EARLIEST_YEAR:
                continue
            url = SEAMLESS_YEAR.format(year=year)
            html = self.fetcher.fetch_with_requests(url)
            rows = _seamless_rows(html, url)
            if not rows:
                raise RuntimeError(
                    f"{self.council_name}: no meetings in the Seamless table at {url}"
                )
            results += [
                row
                for row in rows
                if datetime.date.fromisoformat(row.date) < self.resolve_from
            ]
        return results


# The archive's meeting names for the same three bodies. The planning
# committee was renamed with each council term: Shire Strategic Planning
# Committee to 2023, Planning and Growth Committee to 2024, then Planning
# Committee (which Resolve calls the Planning Standing Committee).
_ARCHIVE_NAMES = {
    "Council": "Council Meeting",
    "Extraordinary Council": "Extraordinary Council Meeting",
    "Sutherland Shire Local Planning Panel": "Sutherland Shire Local Planning Panel",
    "Shire Strategic Planning Committee": "Shire Strategic Planning Committee",
    "Planning and Growth Committee": "Planning and Growth Committee",
    "Planning Committee": "Planning Committee",
}

# A row's Business Papers cell also holds declarations of interest,
# additional reports and supplementary documents; its Minutes cell holds the
# panel's "Report of Meeting" (its minutes) and sometimes a supplementary
# document. Link texts are typed by hand: "Buniess Paper", "Business
# paper", "Business Paper.pdf", "Report of the Meeting".
_BUSINESS_PAPER = re.compile(r"\b(business|buniess)\s+papers?\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b|\breport\s+of\s+(the\s+)?meeting\b", re.IGNORECASE)
_NOT_THE_PAPER = re.compile(
    r"declaration|additional|supplementary|addendum|late\s+item|attachment",
    re.IGNORECASE,
)


def _seamless_rows(html: str, url: str) -> list[ScraperReturn]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for row in soup.find_all("tr", class_="minutes-table-row"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        name = _ARCHIVE_NAMES.get(cells[1].get_text(" ", strip=True))
        if not name:
            continue
        date = datetime.datetime.strptime(
            cells[0].get_text(strip=True), "%d/%m/%Y"
        ).date()
        agenda_url = _paper(cells[2], _BUSINESS_PAPER, url)
        # The panel's 19 August 2025 Report of Meeting is filed in the
        # Business Papers cell, so that cell is the fallback for minutes.
        minutes_url = _paper(cells[3], _MINUTES, url) or _paper(cells[2], _MINUTES, url)
        if agenda_url and _misfiled(agenda_url, date):
            # The panel's 16 September 2025 meeting has a second row whose
            # business paper is the 7 October 2025 one.
            continue
        if not (agenda_url or minutes_url):
            continue
        results.append(
            ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=None,
                webpage_url=url,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
            )
        )
    return results


_FILE_DATE = re.compile(r"/(\d{4}-\d{2}-\d{2})-[^/]*$")


def _misfiled(url: str, date: datetime.date) -> bool:
    """Whether a paper's filename is dated, and for another day."""
    match = _FILE_DATE.search(url)
    return bool(match) and match.group(1) != date.isoformat()


def _paper(cell, label: re.Pattern, base_url: str) -> Optional[str]:
    for link in cell.find_all("a", href=True):
        text = link.get_text(" ", strip=True)
        if not link["href"].lower().endswith(".pdf"):
            continue
        if label.search(text) and not _NOT_THE_PAPER.search(text):
            return urljoin(base_url, link["href"])
    return None
