import datetime
import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://centraldesert.nt.gov.au"
_COUNCIL_URL = f"{_BASE_URL}/our-council/agendas-and-minutes/council"

# Central Desert's Joomla site keeps Council papers in a DOCman category per
# year (/our-council/agendas-and-minutes/council/2026), twenty documents to a
# page and paged with ?start=20. Each document is titled with its meeting and
# kind: "Ordinary Council Meeting - Friday, 25 September 2026 - Agenda",
# "... - Unconfirmed Minutes". Its /download address answers with the PDF.
#
# Only the Council category is read. The Committees and Local Authorities
# categories hold the papers of advisory bodies, not decisions of Council, and
# in the NT planning decisions are not the council's to make anyway.
#
# robots.txt names AI crawlers (ClaudeBot, GPTBot and others) and disallows
# them everything; the `*` group, which is this scraper's, disallows nothing.
_DOCUMENT_PATH = re.compile(r"/agendas-and-minutes/council/\d{4}/[a-z0-9-]+$")
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# Titles write the date both ways round, sometimes with ordinals, and a
# two-day meeting as "Thursday & Friday, 25 & 26 September 2025".
_DAY_FIRST = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*&\s*\d{{1,2}}(?:st|nd|rd|th)?)?\s+{_MONTH}\.?,?\s+(\d{{4}})",
    re.IGNORECASE,
)
_MONTH_FIRST = re.compile(
    rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", re.IGNORECASE
)
_TWO_DAYS = re.compile(r"(?<!\d)\d{1,2}\s*&\s*\d{1,2}\s", re.IGNORECASE)
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_SPECIAL = re.compile(r"special", re.IGNORECASE)
_PART = re.compile(r"\bpart\s+(\d+)", re.IGNORECASE)


def _title_date(title: str) -> Optional[datetime.date]:
    match = _DAY_FIRST.search(title)
    if match:
        day, month, year = match.groups()
    else:
        match = _MONTH_FIRST.search(title)
        if not match:
            return None
        month, day, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
    except ValueError:
        return None


@register_scraper
class CentralDesertScraper(BaseScraper):
    def __init__(self):
        super().__init__("central_desert", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _year_documents(self, year: int) -> list[tuple[str, str]]:
        """(title, document page URL) for every document in a year's category.

        A year whose category does not exist yet (2027 until its first
        meeting) answers 404. That is an empty year for a future year, and
        for the current one only before March, when its first meeting may
        not have been filed. A 404 for the current year later than that
        means the categories moved, and is left to raise like any other
        failure, since it would drop the year.
        """
        url = f"{_COUNCIL_URL}/{year}"
        documents: list[tuple[str, str]] = []
        while url:
            try:
                html = self.fetcher.fetch_with_requests(url)
            except requests.HTTPError as error:
                response = getattr(error, "response", None)
                status = response.status_code if response is not None else None
                not_found = status == 404 or str(error).startswith("404")
                today = clock.today()
                empty_year = year > today.year or (
                    year == today.year and today.month < 3
                )
                if not_found and empty_year and not documents:
                    self.logger.info(f"{self.council_name}: no category yet for {year}")
                    return []
                raise
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = urljoin(url, link["href"])
                title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
                if _DOCUMENT_PATH.search(href) and title:
                    documents.append((title, href))
            # DOCman's pager links the next page as "?start=20"; the current
            # page is not a link.
            url = None
            for link in soup.find_all("a", href=re.compile(r"[?&]start=\d+")):
                start = int(re.search(r"start=(\d+)", link["href"]).group(1))
                if start == len(documents):
                    url = urljoin(_BASE_URL, link["href"])
                    break
        return documents

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # (date, special) -> {"agenda": [(rank, url)], "minutes": [(rank, url)]}
        meetings: dict[tuple[datetime.date, bool], dict[str, list]] = {}
        for year in sorted(wanted):
            for title, page_url in self._year_documents(year):
                # The /download address serves the file; the document's own
                # page is an HTML wrapper around a "Download" button.
                slug = page_url.rsplit("/", 1)[-1]
                download_url = (
                    f"{_BASE_URL}/our-council/agendas-and-minutes/{slug}/download"
                )
                date = _title_date(title)
                if date is None:
                    self.logger.warning(
                        f"{self.council_name}: undated {title!r}; skipped"
                    )
                    continue
                if _MINUTES.search(title):
                    kind = "minutes"
                    # Confirmed minutes supersede unconfirmed ones, and the
                    # 2023 "Minutes of the ... meeting held on ..." uploads
                    # duplicate the confirmed copies beside them.
                    rank = 0 if _CONFIRMED.search(title) else 1
                elif _AGENDA.search(title):
                    kind = "agenda"
                    # Pre-2020 agendas came in parts; part 1 holds the
                    # agenda itself.
                    part = _PART.search(title)
                    rank = int(part.group(1)) if part else 0
                else:
                    continue
                papers = meetings.setdefault((date, bool(_SPECIAL.search(title))), {})
                papers.setdefault(kind, []).append((rank, download_url))
                if kind == "agenda" and _TWO_DAYS.search(title):
                    papers["two_days"] = True

        self._join_two_day_meetings(meetings)

        results = []
        for (date, special), papers in sorted(meetings.items()):
            if date.year not in wanted:
                continue
            agenda = min(papers.get("agenda", []), default=None)
            minutes = min(papers.get("minutes", []), default=None)
            agenda_url = agenda[1] if agenda else None
            minutes_url = minutes[1] if minutes else None
            results.append(
                ScraperReturn(
                    name=(
                        "Special Council Meeting"
                        if special
                        else "Ordinary Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=f"{_COUNCIL_URL}/{date.year}",
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one empty answer that is not a fault: production asks for
            # the current year alone, and before March a small council may not
            # have posted its first paper of the year. Any other empty result
            # means the pages moved or stopped parsing, and returning [] would
            # read downstream as a successful night with no meetings.
            today = clock.today()
            if min(wanted) > today.year or (
                min(wanted) == today.year and today.month < 3
            ):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(wanted)}"
                )
            else:
                raise RuntimeError(
                    f"{self.council_name}: no meetings with documents for "
                    f"{sorted(wanted)}; the pages may have changed"
                )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _join_two_day_meetings(meetings: dict) -> None:
        """Move a two-day meeting's minutes onto its agenda.

        "Ordinary Council Meeting - Thursday & Friday, 25 & 26 September 2025
        - Agenda" is filed under its first day, the 25th; its minutes are
        dated by the day the meeting closed, "Friday, 26 September 2025".
        Joined only for an agenda titled with two days, with no minutes of
        its own, and minutes the next day with no agenda.
        """
        for (date, special), papers in list(meetings.items()):
            if not papers.get("two_days") or "minutes" in papers:
                continue
            next_day = (date + datetime.timedelta(days=1), special)
            other = meetings.get(next_day)
            if other and "agenda" not in other and "minutes" in other:
                papers["minutes"] = meetings.pop(next_day)["minutes"]
