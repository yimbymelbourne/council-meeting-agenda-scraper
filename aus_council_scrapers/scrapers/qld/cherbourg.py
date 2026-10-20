import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://cherbourg.qld.gov.au"
# One WordPress page holds every paper back to 2012, in a `div.appendix` per
# financial year ("Meetings Agendas, Working Papers & Minutes 2025-26"), each
# a run of rows: a Download link and a hand-typed description ("Agenda 20 &
# 21 May", "Minutes – July 17", "Working Papers 18 & 19 Sept"). Most
# ordinary meetings sit over two days; a meeting is dated by its first.
_LISTING_URL = f"{_BASE_URL}/council/your-council/"

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_ORDINAL = r"(?:st|nd|rd|th)?"
# "20 & 21 May", "15 – 26 March", "21st & 22nd June", "15 May & 16 May".
_DAY_FIRST = re.compile(
    r"(?<![\d(])(\d{1,2})" + _ORDINAL + r"(?:\s*(?:&|-|–|and)\s*\d{1,2}" + _ORDINAL + r")?\s+" + _MONTH + r"\b",
    re.IGNORECASE,
)
# "July 17", "March 13 & 14", "January 20 & 21st".
_MONTH_FIRST = re.compile(r"\b" + _MONTH + r"\s+(\d{1,2})" + _ORDINAL + r"\b", re.IGNORECASE)
_FILE_DATE = re.compile(r"(?<!\d)(\d{1,2})(?:-\d{1,2})?-" + _MONTH + r"-(\d{4})", re.IGNORECASE)
_FY = re.compile(r"(\d{4})\s*-\s*(\d{2,4})\s*$")
# A volume number in front of the date ("Working Papers 2 March 13 & 14",
# "Working Papers 1(One). 15 February", "Agenda (2) – 24 April"), which
# would otherwise read as the 2nd or 1st of the month.
_VOLUME = re.compile(
    r"\b(working\s+papers?\s*)(?:\(?[1-3]\)?(?:\s*\((?:one|two|three)\))?\.?(?=[\s–-]|$))"
    r"|\b(agenda\s*)\([1-9]\)",
    re.IGNORECASE,
)


@dataclass
class _Paper:
    kind: str  # "agenda", "working" or "minutes"
    url: str
    body: str
    year: int
    month: int
    day: int


def _body(label: str) -> str:
    if re.search(r"budget", label, re.IGNORECASE):
        return "Special Budget Meeting"
    if re.search(r"post[\s-]*election", label, re.IGNORECASE):
        return "Post Election Meeting"
    if re.search(r"special", label, re.IGNORECASE):
        return "Special Meeting"
    return "Ordinary Council Meeting"


def _kind(label: str) -> Optional[str]:
    """Which paper a row is, or None for notices, reports and policies.

    "Working Papers" is the reports pack that goes with the agenda. "Agenda
    & Working Papers July 19" is one combined paper, and counts as the
    agenda; "Working Papers – Agenda 19 & 20 June" is the pack alone.
    """
    text = label.lower()
    if "minutes" in text:
        return "minutes"
    if "working paper" in text and not text.startswith("agenda"):
        return "working"
    if "agenda" in text:
        return "agenda"
    return None


def _day_month(label: str, url: str) -> Optional[tuple[int, int]]:
    label = _VOLUME.sub(lambda m: m.group(1) or m.group(2), label)
    for pattern, day_group, month_group in ((_DAY_FIRST, 1, 2), (_MONTH_FIRST, 2, 1)):
        match = pattern.search(label)
        if match:
            return int(match.group(day_group)), _MONTHS[match.group(month_group)[:3].lower()]
    match = _FILE_DATE.search(unquote(url.rsplit("/", 1)[-1]))
    if match:
        return int(match.group(1)), _MONTHS[match.group(2)[:3].lower()]
    return None


@register_scraper
class CherbourgScraper(BaseScraper):
    def __init__(self):
        super().__init__("cherbourg", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _papers(self, html: str) -> list[_Paper]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        papers = []
        for section in soup.select("div.appendix"):
            heading = section.find(["h2", "h3", "h4"])
            fy = _FY.search(heading.get_text(" ", strip=True)) if heading else None
            if not fy:
                continue
            first_year = int(fy.group(1))
            for row in section.select(".item"):
                anchor = row.find("a", href=True)
                description = row.select_one(".description")
                if not anchor or not description:
                    continue
                url = urljoin(_LISTING_URL, anchor["href"].strip())
                # "MINUTES – April 15th 2019" in 2019-20 links the April 2020
                # minutes already listed above it.
                if url in seen or not url.lower().endswith(".pdf"):
                    continue
                seen.add(url)
                label = description.get_text(" ", strip=True)
                kind = _kind(label)
                when = _day_month(label, url) if kind else None
                if not when:
                    continue
                day, month = when
                # The section's financial year, not a year in the label or
                # file name: 2023-24's "Minutes 15 & 16 November" is filed
                # as `5.-15-16-November-2024.pdf`.
                year = first_year if month >= 7 else first_year + 1
                # The labels are typed by hand, so a "31 June" would
                # otherwise raise in _meetings and fail the whole council
                # for one paper.
                try:
                    datetime.date(year, month, day)
                except ValueError:
                    self.logger.warning(
                        f"{self.council_name}: {label!r} gives no real date "
                        f"({day}/{month}/{year}); skipped {url}"
                    )
                    continue
                papers.append(_Paper(kind, url, _body(label), year, month, day))
        return papers

    @staticmethod
    def _meetings(papers: list[_Paper]) -> list[dict]:
        """Group papers into meetings.

        Within a month, one meeting of a type pairs its papers whatever days
        their labels give, and the minutes' day wins: "Agenda 16 & 18 May"
        2023 is `AGENDA-17-18-May-2023.pdf`, minuted as 17 & 18 May.
        Otherwise papers pair on their exact day. A repeat of the same paper
        for one day ("Agenda (1)", "(2)", "(3)" for 24 April 2024, the 13 &
        14 March 2024 minutes listed twice) keeps the first.
        """
        groups: dict[tuple[int, int, str], dict[str, dict[int, str]]] = {}
        for paper in papers:
            by_kind = groups.setdefault((paper.year, paper.month, paper.body), {})
            by_kind.setdefault(paper.kind, {}).setdefault(paper.day, paper.url)

        meetings = []
        for (year, month, body), by_kind in groups.items():
            days = sorted({day for docs in by_kind.values() for day in docs})
            if all(len(docs) == 1 for docs in by_kind.values()):
                # One meeting this month: collapse the label days.
                day = next(iter(by_kind.get("minutes", {})), days[0])
                merged = {kind: next(iter(docs.values())) for kind, docs in by_kind.items()}
                slots = {day: merged}
            else:
                slots = {
                    day: {kind: docs[day] for kind, docs in by_kind.items() if day in docs}
                    for day in days
                }
            for day, docs in slots.items():
                agenda = docs.get("agenda") or docs.get("working")
                minutes = docs.get("minutes")
                if not (agenda or minutes):
                    continue
                meetings.append(
                    {
                        "date": datetime.date(year, month, day),
                        "name": body,
                        "agenda": agenda,
                        "minutes": minutes,
                    }
                )
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: this page is the only request, and failing quietly
        # would report the council as having no meetings.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        papers = [p for p in self._papers(html) if p.year in wanted]

        results = []
        for meeting in sorted(self._meetings(papers), key=lambda m: (m["date"], m["name"])):
            results.append(
                ScraperReturn(
                    name=meeting["name"],
                    date=meeting["date"].isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=meeting["agenda"],
                    minutes_url=meeting["minutes"],
                    download_url=meeting["agenda"] or meeting["minutes"],
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
