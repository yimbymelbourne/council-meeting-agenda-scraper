import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://brewarrina.nsw.gov.au"
# Two WordPress/Elementor pages, business papers (agendas) on one and
# minutes on the other, each an accordion with a tab per year holding one
# linked paragraph per meeting. Agendas and minutes are paired here.
_AGENDAS_URL = f"{_BASE_URL}/council/council-meetings/business-paper/"
_MINUTES_URL = f"{_BASE_URL}/council/council-meetings/minutes/"

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# "25 August Ordinary Council Meeting", "Ordinary Business Meeting 10
# January 2022", or, on the 2025–2026 minutes, just "August Ordinary Council
# Meeting" with no day.
_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})\s+" + _MONTH + r"\b", re.IGNORECASE)
_MONTH_ONLY = re.compile(r"\b" + _MONTH + r"\b", re.IGNORECASE)
# "Extraordinary" and "Extra Ordinary"; everything else is an ordinary
# meeting ("Ordinary Council Meeting", "Ordinary Business Meeting").
_EXTRAORDINARY = re.compile(r"extra\s*-?\s*ordinary", re.IGNORECASE)


@dataclass
class _Paper:
    kind: str  # "agenda" or "minutes"
    url: str
    extraordinary: bool
    year: int
    month: int
    day: Optional[int]


@register_scraper
class BrewarrinaScraper(BaseScraper):
    def __init__(self):
        super().__init__("brewarrina", "NSW", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _papers(html: str, kind: str, page_url: str) -> list[_Paper]:
        soup = BeautifulSoup(html, "html.parser")
        papers = []
        for item in soup.select(".eael-accordion-list"):
            header = item.select_one(".eael-accordion-header")
            content = item.select_one(".eael-accordion-content")
            year_text = header.get_text(strip=True) if header else ""
            # Skips the theme's unused "Accordion Tab Title" placeholders.
            if not content or not re.fullmatch(r"\d{4}", year_text):
                continue
            # The tab year, not the upload path: the 2022–2023 papers were
            # all uploaded to /2024/04/.
            year = int(year_text)
            for anchor in content.find_all("a", href=True):
                url = urljoin(page_url, anchor["href"].strip())
                if not url.lower().endswith(".pdf"):
                    continue
                # The label is the paragraph, which the link may only
                # partly cover.
                block = anchor.find_parent(["p", "li"]) or anchor
                label = block.get_text(" ", strip=True)
                day_month = _DAY_MONTH.search(label)
                if day_month:
                    day, month = int(day_month.group(1)), _MONTHS[day_month.group(2)[:3].lower()]
                else:
                    month_only = _MONTH_ONLY.search(label)
                    if not month_only:
                        continue
                    day, month = None, _MONTHS[month_only.group(1)[:3].lower()]
                papers.append(
                    _Paper(
                        kind=kind,
                        url=url,
                        extraordinary=bool(_EXTRAORDINARY.search(label)),
                        year=year,
                        month=month,
                        day=day,
                    )
                )
        return papers

    def _meetings(self, papers: list[_Paper]) -> list[dict]:
        """Pair business papers with minutes into meetings.

        Within a month, meetings of one type pair when there is exactly one
        paper of each kind, and the minutes' day wins where the two labels
        disagree: "24 July Ordinary Council Meeting" links a business paper
        whose cover says Tuesday 23 July 2024, which the minutes label has
        right. Day-less minutes ("August Ordinary Council Meeting") take the
        business paper's day. Anything else pairs on an exact date only.
        """
        groups: dict[tuple[int, int, bool], list[_Paper]] = {}
        for paper in papers:
            groups.setdefault((paper.year, paper.month, paper.extraordinary), []).append(paper)

        meetings = []
        for (year, month, extraordinary), group in groups.items():
            agendas = [p for p in group if p.kind == "agenda"]
            minutes = [p for p in group if p.kind == "minutes"]
            if len(agendas) == 1 and len(minutes) == 1:
                pairs = [(agendas[0], minutes[0])]
            else:
                pairs = []
                unmatched = list(minutes)
                for agenda in agendas:
                    match = next(
                        (m for m in unmatched if m.day is not None and m.day == agenda.day), None
                    )
                    if match:
                        unmatched.remove(match)
                    pairs.append((agenda, match))
                pairs.extend((None, m) for m in unmatched)

            for agenda, minute in pairs:
                day = (minute.day if minute and minute.day else None) or (agenda.day if agenda else None)
                if day is None:
                    # A day-less minutes paper with no business paper to date
                    # it. Never given an invented day.
                    self.logger.warning(
                        f"{self.council_name}: cannot date {minute.url}; skipped"
                    )
                    continue
                try:
                    date = datetime.date(year, month, day)
                except ValueError:
                    self.logger.warning(
                        f"{self.council_name}: impossible date {day}/{month}/{year} "
                        f"for {(agenda or minute).url}; skipped"
                    )
                    continue
                meetings.append(
                    {
                        "date": date,
                        "extraordinary": extraordinary,
                        "agenda": agenda.url if agenda else None,
                        "minutes": minute.url if minute else None,
                    }
                )
        return meetings

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Both left to raise: either page failing would quietly drop half of
        # every meeting's papers.
        papers = self._papers(
            self.fetcher.fetch_with_requests(_AGENDAS_URL), "agenda", _AGENDAS_URL
        ) + self._papers(
            self.fetcher.fetch_with_requests(_MINUTES_URL), "minutes", _MINUTES_URL
        )
        papers = [p for p in papers if p.year in wanted]

        results = []
        for meeting in sorted(self._meetings(papers), key=lambda m: (m["date"], m["extraordinary"])):
            agenda_url, minutes_url = meeting["agenda"], meeting["minutes"]
            results.append(
                ScraperReturn(
                    name=(
                        "Extraordinary Council Meeting"
                        if meeting["extraordinary"]
                        else "Ordinary Council Meeting"
                    ),
                    date=meeting["date"].isoformat(),
                    time=None,
                    webpage_url=_AGENDAS_URL if agenda_url else _MINUTES_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
