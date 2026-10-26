import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://southperth.wa.gov.au"
_LISTING_URL = "https://southperth.wa.gov.au/about-us/council/council-meetings"

# South Perth (Sitefinity) serves a year of meetings on one page, chosen with
# `?year=`. The page is a set of tabs—Scheduled Meetings, Past Meetings,
# then one per meeting type—each a Date | Time | Meeting | Documents table
# linking the PDFs directly. So a year costs one request.
#
# Three things about those tables shape the parsing:
#
# * The tabs overlap: a meeting appears under Past Meetings and again under
#   its type, so rows are de-duplicated.
# * An agenda briefing and the council meeting it prepares are grouped as a
#   nested table inside one outer row, so only rows whose cells are their own
#   (`recursive=False`) are read, or the pair would be read twice over.
# * Scheduled Meetings always shows the upcoming meetings, whatever `?year=`
#   asks for, so each page is filtered to rows dated in the year it was asked
#   for. Upcoming meetings are still found, on their own year's page.
#
# Kalamunda is also Sitefinity, but its meeting list is a different widget
# (search-result cards, paged by path) with nothing in common at the markup
# level, so the two do not share code.

# Each meeting's documents are the agenda, the minutes, and a long tail of
# attachments ("Attachments - Part 1(a) - 10.3.1"), late reports, briefing
# notes, audio and annual reports. The agenda is not always plainly labelled:
# "Agenda OCM", "SCM Public Agenda 20260814".
_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
_NOT_THE_PAPERS = re.compile(
    r"attach|late report|notes|briefing|item\b|audio|report|presentation",
    re.IGNORECASE,
)
# "Agenda (PDF 1Mb)"—the size note is not part of the label.
_SIZE_NOTE = re.compile(r"\s*\((?:pdf|docx?)[^)]*\)\s*$", re.IGNORECASE)
_TIME = re.compile(r"(\d{1,2})[.:](\d{2})\s*([AP]M)", re.IGNORECASE)


@register_scraper
class SouthPerthScraper(BaseScraper):
    def __init__(self):
        council = "south_perth"
        state = "WA"
        base_url = _BASE_URL
        super().__init__(council, state, base_url)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _papers(cell, page_url: str) -> tuple[Optional[str], Optional[str]]:
        agenda = minutes = None
        agenda_exact = minutes_exact = False
        for link in cell.find_all("a", href=True):
            label = _SIZE_NOTE.sub(
                "", re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            )
            if _NOT_THE_PAPERS.search(label):
                continue
            href = urljoin(page_url, link["href"])
            # A plainly labelled document wins over a variant; otherwise the
            # first one listed is taken.
            if _MINUTES_LABEL.search(label):
                exact = label.lower() == "minutes"
                if minutes is None or (exact and not minutes_exact):
                    minutes, minutes_exact = href, exact
            elif _AGENDA_LABEL.search(label):
                exact = label.lower() == "agenda"
                if agenda is None or (exact and not agenda_exact):
                    agenda, agenda_exact = href, exact
        return agenda, minutes

    def _meetings(self, html: str, page_url: str, year: int):
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all("tr"):
            date_cell = row.find("td", class_="sp-meetings__date", recursive=False)
            documents = row.find("td", class_="sp-meetings__documents", recursive=False)
            if date_cell is None or documents is None:
                continue
            try:
                date = parse_date(
                    date_cell.get_text(" ", strip=True), dayfirst=True
                ).date()
            except (ValueError, OverflowError):
                continue
            if date.year != year:
                continue

            agenda_url, minutes_url = self._papers(documents, page_url)
            if not agenda_url and not minutes_url:
                # "Not yet published", or a briefing with only its notes.
                continue

            # The type is in <strong>; a special meeting follows it with a
            # paragraph on its purpose, which is not part of the name.
            description = row.find("td", class_="sp-meetings__desc", recursive=False)
            heading = description.find("strong") if description else None
            name = (
                re.sub(r"\s+", " ", (heading or description).get_text(" ", strip=True))
                if description
                else "Council Meeting"
            )

            time_cell = row.find("td", class_="sp-meetings__time", recursive=False)
            match = (
                _TIME.search(time_cell.get_text(" ", strip=True)) if time_cell else None
            )
            time = (
                f"{int(match.group(1))}:{match.group(2)} {match.group(3).upper()}"
                if match
                else None
            )

            yield ScraperReturn(
                name=name,
                date=date.isoformat(),
                time=time,
                webpage_url=page_url,
                agenda_url=agenda_url,
                minutes_url=minutes_url,
                download_url=agenda_url or minutes_url,
            )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        # A year that cannot be fetched is logged and skipped. But if nothing
        # at all comes back and a fetch failed, the failure is raised:
        # returning [] would report a blocked or down site as a council with
        # no meetings. Production asks for one year, so one request.
        last_error: Optional[Exception] = None
        for year in sorted(wanted, reverse=True):
            url = f"{_LISTING_URL}?year={year}"
            try:
                html = self.fetcher.fetch_with_requests(url)
            except Exception as e:
                last_error = e
                self.logger.warning(f"Could not read the {year} meetings: {e}")
                continue
            for meeting in self._meetings(html, url, year):
                key = (
                    meeting.date,
                    meeting.name,
                    meeting.agenda_url,
                    meeting.minutes_url,
                )
                if key in seen:
                    continue
                seen.add(key)
                results.append(meeting)

        if not results and last_error is not None:
            raise last_error
        if not results:
            self.logger.warning(f"{self.council_name} scraper found no meetings")
        else:
            self.logger.info(
                f"{self.council_name} scraper found {len(results)} meetings"
            )
        return results
