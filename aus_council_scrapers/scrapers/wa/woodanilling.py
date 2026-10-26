import datetime
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_date, find_month
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.pdf_dates import meeting_date_from_papers

_BASE_URL = "https://www.woodanilling.wa.gov.au"
_INDEX_URL = f"{_BASE_URL}/past-council-meetings.aspx"

# A CouncilConnect (SparkCMS) site whose meetings module is unused. Meetings
# are hand-built content pages instead: one page per year, with names that
# follow no pattern (2025-agendas-and-minutes.aspx, 2022--minutes-and-
# agenda.aspx, council-meeting-2021.aspx), linked from the index page—and the
# current year from the site menu's "Agendas & Minutes", which every page
# carries. Year pages come in two shapes:
#
#   - 2023 on: a heading per meeting ("Ordinary Council Meeting - 18 August
#     2026") and a link to a page per meeting (2026-aug-ocm.aspx), which holds
#     the papers. Each meeting costs a request, so only Council meetings
#     (ordinary and special) are fetched: the audit committee and electors'
#     meetings would add a fifth again to a year that is already ~16 requests.
#   - 2020 to 2022: the papers are linked from the year page itself, under a
#     heading per meeting (or per month, before 2022).
#
# Papers are /documents/<id>/<slug>, which serve the PDF itself. robots.txt
# disallows /Profiles/woodanilling/Assets/ModuleData/, which none of these
# pages or papers use.
#
# Labels say what each paper is and when its meeting was ("Agenda to OCM 18
# August 2026", "Unconfirmed Minutes SCM 30 August 2022", "E-Minutes 19
# October 2021"). A paper whose label or slug names another day is another
# meeting's: the 29 July 2023 special meeting's "Agenda SCM 29 July 2023"
# links /documents/20987/agenda-ocm-21-march-2023, and most 2026 meeting pages
# carry a leftover unlabelled link to the 16 December 2025 agenda.

_YEAR_LINK = re.compile(r"Council Meetings?\s+(20\d\d)", re.IGNORECASE)
_DOCUMENT = re.compile(r"/documents/\d+/")
_NOT_A_PAPER = re.compile(r"attach|appendi|briefing|pre-agenda|audio|notice|recording", re.IGNORECASE)
# "Special Council Meeting Agenda & Attachments June 2020" is the agenda,
# with its attachments bound in.
_BUNDLED = re.compile(r"agenda\s*(?:&|and)\s*attachments", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_AMENDED = re.compile(r"amended", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b|\bSCM\b", re.IGNORECASE)
_OTHER_BODY = re.compile(r"audit|committee|elector|\bAEM\b|\bACM\b", re.IGNORECASE)
_SLASHED_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")


def _date_in(text: str) -> Optional[datetime.date]:
    """A full date in a label or slug: "18 August 2026", "23/01/2024"."""
    found = find_date(re.sub(r"[-_]+", " ", text))
    if found:
        return found[0]
    match = _SLASHED_DATE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    return None


def _meeting_type(text: str) -> Optional[str]:
    """Ordinary or special Council meeting, or None for any other body."""
    if _OTHER_BODY.search(text):
        return None
    return "Special Council Meeting" if _SPECIAL.search(text) else "Ordinary Council Meeting"


@dataclass
class _Paper:
    kind: str
    label: str
    url: str


# Papers whose label and slug both name the wrong day, checked against the
# paper itself. "Special Council Meeting Minutes 4 November 2021"
# (/documents/20806/) is headed "Minutes 11 November 2021" and records the
# budget going to "a Special Council Meeting directly after the Audit
# Committee Meeting on the same day", Thursday 11 November; only the report
# form bound inside it still says 04 November.
_DATE_CORRECTIONS = {
    "/documents/20806/": datetime.date(2021, 11, 11),
}


def _paper_dates(paper: _Paper) -> set[datetime.date]:
    """The dates a paper's label and slug name. Two means one is wrong."""
    for path, date in _DATE_CORRECTIONS.items():
        if path in paper.url:
            return {date}
    return {d for d in (_date_in(paper.label), _date_in(paper.url)) if d}


def _papers(links) -> list[_Paper]:
    papers = []
    for label, url in links:
        if not label or (_NOT_A_PAPER.search(label) and not _BUNDLED.search(label)):
            # An unlabelled link is the stray left on most 2026 pages.
            continue
        if _MINUTES.search(label):
            papers.append(_Paper("minutes", label, url))
        elif _AGENDA.search(label):
            papers.append(_Paper("agenda", label, url))
    return papers


def _pick(papers: list[_Paper], kind: str) -> Optional[str]:
    """The amended agenda over the first issue; confirmed minutes over
    unconfirmed."""
    candidates = [p for p in papers if p.kind == kind]
    if not candidates:
        return None
    preferred = _AMENDED if kind == "agenda" else _CONFIRMED
    for paper in candidates:
        if preferred.search(paper.label):
            return paper.url
    return candidates[0].url


@register_scraper
class WoodanillingScraper(BaseScraper):
    # One production year measured 28 s from home (15 requests).
    expected_seconds = 28.0

    def __init__(self):
        super().__init__("woodanilling", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _page(self, url: str):
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
        content = soup.select_one("div.cp-placeholder")
        if content is None:
            raise ValueError(f"{self.council_name}: no content area on {url}")
        return soup, content

    def _year_pages(self) -> dict[int, str]:
        soup, content = self._page(_INDEX_URL)
        pages = {}
        for link in content.find_all("a", href=True):
            match = _YEAR_LINK.search(link.get_text(" ", strip=True))
            if match:
                pages[int(match.group(1))] = urljoin(_INDEX_URL, link["href"])
        # The current year is only in the menu.
        for link in soup.find_all("a", href=True):
            if link.get_text(" ", strip=True) == "Agendas & Minutes":
                match = re.search(r"(20\d\d)", link["href"])
                if match:
                    pages.setdefault(int(match.group(1)), urljoin(_INDEX_URL, link["href"]))
        if not pages:
            raise ValueError(f"{self.council_name}: no year pages linked from {_INDEX_URL}")
        return pages

    @staticmethod
    def _sections(content) -> list[tuple[str, list[tuple[str, str]], list[str]]]:
        """(heading, [(label, document URL)], [meeting page URL]) per heading."""
        sections: list[tuple[str, list, list]] = []
        for element in content.find_all(["h2", "h3", "a"]):
            if element.name in ("h2", "h3"):
                sections.append((element.get_text(" ", strip=True), [], []))
                continue
            if not sections or not element.get("href"):
                continue
            url = urljoin(_BASE_URL, element["href"].strip())
            label = element.get_text(" ", strip=True)
            if _DOCUMENT.search(url):
                sections[-1][1].append((label, url))
            elif re.search(r"view|click", label, re.IGNORECASE) and url.endswith(".aspx"):
                sections[-1][2].append(url)
        return sections

    def _meeting_page(self, url: str, heading: str) -> Optional[ScraperReturn]:
        _, content = self._page(url)
        title = content.find("h2")
        title_text = title.get_text(" ", strip=True) if title else heading
        name = _meeting_type(title_text) or _meeting_type(heading)
        links = [
            (a.get_text(" ", strip=True), urljoin(_BASE_URL, a["href"].strip()))
            for a in content.find_all("a", href=True)
            if _DOCUMENT.search(a["href"])
        ]
        # The audit committee's papers share some Council meeting pages
        # ("ACM Agenda 20 February 2024").
        papers = [p for p in _papers(links) if _meeting_type(p.label) is not None]
        # The page title and the year page's heading usually agree. When they
        # do not, the one the papers name wins: the February 2024 page is
        # titled 23 February, and its heading and every paper say 20.
        candidates = [d for d in (_date_in(title_text), _date_in(heading)) if d]
        named = [d for d in candidates if any(_paper_dates(p) == {d} for p in papers)]
        date = (named or candidates or [None])[0]
        if date is None or name is None:
            self.logger.warning(f"{self.council_name}: cannot date or type {url}; skipped")
            return None
        papers = [paper for paper in papers if _paper_dates(paper) <= {date}]
        return self._result(name, date, url, papers)

    @staticmethod
    def _result(name, date, url, papers) -> Optional[ScraperReturn]:
        agenda_url = _pick(papers, "agenda")
        minutes_url = _pick(papers, "minutes")
        if not agenda_url and not minutes_url:
            return None
        return ScraperReturn(
            name=name,
            date=date.isoformat(),
            time=None,
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def _inline(self, sections, page_url: str, year: int) -> list[ScraperReturn]:
        """Meetings from a year page that links its papers directly.

        Before 2022 a heading covers a month ("Ordinary Council Meeting -
        November 2021") and can hold a special meeting's papers as well, so
        each paper is dated and typed from its own label, falling back to a
        dated heading. A paper dated to the month only ("E-Minutes November
        2021") takes the day of its counterpart of the same type that month
        when there is exactly one ("E-Agenda March 2020" from "E-Minutes 17
        March 2020"). Failing that it is dated from its PDF's first page
        (pdf_dates.py), the month's papers of one meeting type together
        when there is one of each, minutes first; a day outside the label's
        month is never taken. Otherwise it is left out. Only these pre-2023
        pages are read this way, so a production year costs no PDF read.
        """
        dated: list[tuple[datetime.date, str, _Paper]] = []
        undated: list[tuple[tuple[int, int], str, _Paper]] = []
        for heading, links, _ in sections:
            heading_type = _meeting_type(heading)
            if heading_type is None:
                continue
            heading_date = _date_in(heading)
            for paper in _papers(links):
                name = _meeting_type(paper.label)
                if name is None:
                    # "Agenda Audit Committee 19 July 2022" under the OCM.
                    continue
                if name == "Ordinary Council Meeting":
                    name = heading_type
                dates = _paper_dates(paper)
                if len(dates) > 1:
                    continue
                date = dates.pop() if dates else None
                if date is None and heading_date and name == heading_type:
                    date = heading_date
                if date:
                    dated.append((date, name, paper))
                    continue
                month = find_month(paper.label) or find_month(heading) or find_month(
                    re.sub(r"[-_]+", " ", paper.url)
                )
                if month:
                    undated.append((month, name, paper))
        pending: dict[tuple, list[_Paper]] = {}
        for month, name, paper in undated:
            days = {
                date
                for date, other_name, other in dated
                if other_name == name and other.kind != paper.kind and (date.year, date.month) == month
            }
            if len(days) == 1:
                dated.append((days.pop(), name, paper))
            elif month[0] == year:
                pending.setdefault((month, name), []).append(paper)
        for (month, name), papers in pending.items():
            kinds = [paper.kind for paper in papers]
            if len(kinds) == len(set(kinds)):
                ordered = sorted(papers, key=lambda p: p.kind != "minutes")
                date = meeting_date_from_papers(
                    self.fetcher, [p.url for p in ordered], *month, logger=self.logger
                )
                found = [(paper, date) for paper in papers]
            else:
                found = [
                    (
                        paper,
                        meeting_date_from_papers(
                            self.fetcher, [paper.url], *month, logger=self.logger
                        ),
                    )
                    for paper in papers
                ]
            for paper, date in found:
                if date:
                    self.logger.info(
                        f"{self.council_name}: {paper.label!r} dated {date} from the PDF"
                    )
                    dated.append((date, name, paper))
                else:
                    self.logger.warning(f"{self.council_name}: cannot date {paper.label!r}; skipped")

        meetings: dict[tuple, list[_Paper]] = {}
        for date, name, paper in dated:
            meetings.setdefault((date, name), []).append(paper)
        results = []
        for (date, name), papers in sorted(meetings.items()):
            result = self._result(name, date, page_url, papers)
            if result:
                results.append(result)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        # Every request is left to raise. A year or meeting page that fails
        # is meetings missing, and with one year a night that would be the
        # whole result.
        for year, page_url in sorted(self._year_pages().items()):
            if year not in wanted:
                continue
            _, content = self._page(page_url)
            sections = self._sections(content)
            if any(pages for _, _, pages in sections):
                for heading, _, pages in sections:
                    if _meeting_type(heading) is None:
                        continue
                    for meeting_url in pages:
                        result = self._meeting_page(meeting_url, heading)
                        if result:
                            results.append(result)
            else:
                results.extend(self._inline(sections, page_url, year))

        results = [r for r in results if r.cleaned_date.year in wanted]
        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
