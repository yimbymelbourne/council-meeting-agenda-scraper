import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://ropergulf.nt.gov.au"
_ARCHIVE_URL = f"{_BASE_URL}/our-council/meetings/council-meetings/archive/{{year}}"

# Roper Gulf's Drupal site lists a year of council meetings per archive page,
# each meeting a `.meeting-item` with its date, a title naming the community
# it sat in ("Council Meeting — Mataranka", since council meets around the
# region), a notes field, and labelled Agenda, Minutes and Attachments
# fields linking the files. The archive page for the current year is the
# same list as the main council-meetings page, upcoming meetings included,
# so one request covers a production year.
#
# Only council meetings are read. The committee meetings page has the same
# shape but holds the Finance and Infrastructure and Audit and Risk
# committees, which report to council rather than decide.
_SPECIAL_NOTE = re.compile(r"special meeting", re.IGNORECASE)
# Special meetings are filed SMC_, SPL_ or SCM, or tagged _EXTRA/_SPECIAL.
_SPECIAL_FILE = re.compile(r"^(?:SMC|SPL|SCM)[_\s]|_(?:EXTRA|SPECIAL)\b", re.IGNORECASE)
# The 14 May 2024 agenda field holds "SCM NOTICE 140524.pdf", the notice of
# a special meeting, and supplementary agendas sit beside the agenda
# (OMC_24062020_AGN_AT_SUP.pdf).
_NOT_AGENDA = re.compile(r"notice|_SUP\b|_SUP\.", re.IGNORECASE)
# The 28 September 2022 minutes were filed under Attachments.
_MINUTES_FILE = re.compile(r"(?:^|_)MIN(?:_|\.|$)", re.IGNORECASE)
# "Please be advised that this Special Meeting of Council has been
# cancelled." (15 November 2024): the agenda stays up, but no meeting sat.
_CANCELLED = re.compile(r"cancel", re.IGNORECASE)


@register_scraper
class RoperGulfScraper(BaseScraper):
    def __init__(self):
        super().__init__("roper_gulf", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _field_links(item, label: str, page_url: str) -> list[str]:
        for field in item.select(".meeting-item__meta-data"):
            name = field.select_one(".meeting-item__meta-data-label")
            if name and name.get_text(strip=True).lower() == label:
                return [
                    requote_uri(urljoin(page_url, a["href"].strip()))
                    for a in field.select(".meeting-item__meta-data-value a[href]")
                ]
        return []

    @staticmethod
    def _field_text(item, label: str) -> str:
        for field in item.select(".meeting-item__meta-data"):
            name = field.select_one(".meeting-item__meta-data-label")
            if name and name.get_text(strip=True).lower() == label:
                value = field.select_one(".meeting-item__meta-data-value")
                return value.get_text(" ", strip=True) if value else ""
        return ""

    @staticmethod
    def _filename(url: str) -> str:
        return unquote(url.rsplit("/", 1)[-1])

    def _meetings(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.select(".meeting-item"):
            date_el = item.select_one(".meeting-item__header-date")
            type_el = item.select_one(".meeting-item__header-meeting-type")
            if not date_el:
                continue
            try:
                date = datetime.datetime.strptime(
                    date_el.get_text(strip=True), "%d %b %Y"
                ).date()
            except ValueError:
                self.logger.warning(
                    f"{self.council_name}: cannot read date {date_el.get_text(strip=True)!r} on {page_url}"
                )
                continue
            title = type_el.get_text(" ", strip=True) if type_el else ""
            # Read from the Notes field alone, not the whole panel, so a file
            # name cannot trip it.
            if _CANCELLED.search(self._field_text(item, "notes")):
                self.logger.info(
                    f"{self.council_name}: {date} meeting cancelled; skipped"
                )
                continue
            # "Council Meeting — Barunga": the part after the dash is where
            # the meeting sat, not its name.
            location: Optional[str] = None
            if "—" in title:
                location = title.split("—", 1)[1].strip() or None

            agendas = [
                url
                for url in self._field_links(item, "agenda", page_url)
                if not _NOT_AGENDA.search(self._filename(url))
            ]
            minutes = self._field_links(item, "minutes", page_url)
            if not minutes:
                stamp = date.strftime("%d%m%Y")
                minutes = [
                    url
                    for url in self._field_links(item, "attachments", page_url)
                    if _MINUTES_FILE.search(self._filename(url))
                    and stamp in self._filename(url)
                ]
            agenda_url = agendas[0] if agendas else None
            minutes_url = minutes[0] if minutes else None
            if not agenda_url and not minutes_url:
                # Upcoming meetings are listed before their papers are.
                continue

            notes = item.select_one(".meeting-item__panel")
            notes_text = notes.get_text(" ", strip=True) if notes else ""
            special = bool(_SPECIAL_NOTE.search(notes_text)) or any(
                _SPECIAL_FILE.search(self._filename(url))
                for url in (agenda_url, minutes_url)
                if url
            )
            results.append(
                ScraperReturn(
                    name=(
                        "Special Council Meeting"
                        if special
                        else "Ordinary Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=location,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        failed = []
        for year in sorted(wanted):
            page_url = _ARCHIVE_URL.format(year=year)
            try:
                html = self.fetcher.fetch_with_requests(page_url)
            except Exception as error:
                self.logger.warning(
                    f"{self.council_name}: could not read {page_url}: {error}"
                )
                failed.append(year)
                continue
            # A year with no meetings yet (2027 in October 2026) is an empty
            # list, not an error.
            results.extend(
                meeting
                for meeting in self._meetings(html, page_url)
                if meeting.date[:4] == str(year)
            )

        if failed and len(failed) == len(wanted):
            raise RuntimeError(
                f"{self.council_name}: no archive page could be read for {failed}"
            )
        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
