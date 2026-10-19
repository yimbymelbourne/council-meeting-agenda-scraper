"""Golden Plains Shire Council (VIC).

Agendas and minutes are on two separate Drupal pages, each a whole history
in one request, and they are joined by meeting date:

- **Meeting Agendas**: an accordion per year (2021 onward), one item per
  meeting ("22 September Council Meeting"), holding the agenda PDF and every
  item attachment. Attachments include other bodies' minutes ("Att 7.2 Audit
  & Risk Committee Unconfirmed Minutes ..."), which are not the Council's.
- **Meeting Minutes**: the current year's Unconfirmed and Confirmed lists,
  then a "Previous Meetings" accordion with an item per year (minutes back to
  August 2021; 2020 is empty, and 2016-2019 hold a few older files).

Labels name the day and month and leave the year to the section, and they
are typed by hand, so they are sometimes wrong where the filename is right.
The minutes labelled "29 December" (2023) are filed as "Council Meeting
Minutes - 19 December 2023" and the meeting was on Tuesday 19 December; the
agenda labelled "23 September" (2021) is `Council Meeting agenda 280921.pdf`
and its minutes are labelled 28 September. So a date in the filename, when
it is within a fortnight of the label's, wins.

**robots.txt disallows `/sites/default/files/`**, where every PDF lives. The
scraper only reads the two listing pages, which are allowed, and records
the PDF links without fetching them.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.goldenplains.vic.gov.au"
_AGENDAS_URL = f"{_BASE_URL}/about-council/council-meetings/meeting-agendas"
_MINUTES_URL = f"{_BASE_URL}/about-council/council-meetings/meeting-minutes"

_MONTH_WORD = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MONTHS = (
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
)

# "20 October Council Meeting", "25 August 2026 Council Meeting".
_LABEL_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s+{_MONTH_WORD}\b(?:\s+(\d{{4}}))?", re.I
)
# Filenames: "... 22 Sept 2026 Public.pdf", "... - Tuesday, 22 February
# 2022.pdf", "... 25.08.2026 Public.pdf", "Council Meeting agenda 280921.pdf".
_FILE_WORDS = re.compile(rf"(?<!\d)(\d{{1,2}})\s+{_MONTH_WORD}\s+(\d{{4}})(?!\d)", re.I)
_FILE_DOTTED = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_FILE_DDMMYY = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")

# How far a filename's date may sit from the label's and still be read as
# the same meeting corrected, not a different one.
_CORRECTION_DAYS = 14

_YEAR_ONLY = re.compile(r"^\s*(\d{4})\s*$")

_AGENDA = re.compile(r"\bagenda\b", re.I)
# Everything else the agenda accordion links for a meeting.
_NOT_THE_AGENDA = re.compile(
    r"attach|\batt\b|\bitem\b|minutes|notice of motion|petition|mayoral minute", re.I
)
_NO_ATTACHMENTS = re.compile(r"\bno\s+attachments(?![a-z])", re.I)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.I)

_SPECIAL_FILE = re.compile(r"special council meeting", re.I)


def _month(word: str) -> int:
    return _MONTHS.index(word[:3].lower()) + 1


def _filename(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])


def _filename_dates(url: str) -> list[datetime.date]:
    name = _filename(url)
    found = []
    for match in _FILE_WORDS.finditer(name):
        found.append((int(match.group(3)), _month(match.group(2)), int(match.group(1))))
    for match in _FILE_DOTTED.finditer(name):
        found.append((int(match.group(3)), int(match.group(2)), int(match.group(1))))
    for match in _FILE_DDMMYY.finditer(name):
        found.append(
            (2000 + int(match.group(3)), int(match.group(2)), int(match.group(1)))
        )
    dates = []
    for year, month, day in found:
        try:
            dates.append(datetime.date(year, month, day))
        except ValueError:
            pass
    return dates


def _meeting_type(label: str, agenda_url: Optional[str] = None) -> str:
    """ "11 November Council Meeting (Mayoral/Deputy Mayoral Election)" ->
    "Council Meeting". The occasion in brackets or after a dash is dropped
    so the name stays a meeting type."""
    text = _LABEL_DATE.sub(" ", label)
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.split(r"\s+[-–—]\s+", text)[0]
    name = re.sub(r"\s+", " ", text).strip() or "Council Meeting"
    # The 20 October 2026 agenda is labelled a plain "Council Meeting" and
    # filed as "Special Council Meeting Agenda 20.10.2026.pdf"; the year's
    # published schedule has no ordinary meeting that day.
    if (
        name.lower() == "council meeting"
        and agenda_url
        and _SPECIAL_FILE.search(_filename(agenda_url))
    ):
        return "Special Council Meeting"
    return name


@register_scraper
class GoldenPlainsScraper(BaseScraper):
    def __init__(self):
        super().__init__("golden_plains", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _date(
        self, label: str, section_year: Optional[int], url: str
    ) -> Optional[datetime.date]:
        match = _LABEL_DATE.search(label)
        labelled = None
        if match:
            year = int(match.group(3)) if match.group(3) else section_year
            if year:
                try:
                    labelled = datetime.date(
                        year, _month(match.group(2)), int(match.group(1))
                    )
                except ValueError:
                    labelled = None
        filed = [
            date
            for date in _filename_dates(url)
            if labelled is None or abs((date - labelled).days) <= _CORRECTION_DAYS
        ]
        if labelled and filed and filed[0] != labelled:
            self.logger.info(
                f"{label!r}: using {filed[0]} from {_filename(url)!r} over {labelled}"
            )
        if filed:
            return filed[0]
        return labelled

    def _agendas(self, html: str) -> dict[datetime.date, tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        found: dict[datetime.date, tuple[str, str]] = {}
        sections = soup.select("div.paragraph--type--pt11-accordion")
        if not sections:
            raise RuntimeError(
                f"{_AGENDAS_URL} has no year accordions; the page markup has changed"
            )
        for section in sections:
            heading = section.select_one(".field--name-field-accordion-title")
            year_match = (
                _YEAR_ONLY.match(heading.get_text(" ", strip=True)) if heading else None
            )
            section_year = int(year_match.group(1)) if year_match else None
            for item in section.select("div.paragraph--type--pt11-1-accordion-item"):
                title = item.select_one(".field--name-field-title")
                label = (
                    re.sub(r"\s+", " ", title.get_text(" ", strip=True))
                    if title
                    else ""
                )
                agenda_url = None
                for link in item.select(".field--name-field-text-box a[href]"):
                    text = f"{link.get_text(' ', strip=True)} {_filename(link['href'])}"
                    # "PUBLIC Council Meeting Agenda - 28 June 2022 - No
                    # Attachments" is the agenda, not an attachment.
                    text = _NO_ATTACHMENTS.sub(" ", text)
                    if _AGENDA.search(text) and not _NOT_THE_AGENDA.search(text):
                        agenda_url = urllib.parse.urljoin(
                            _AGENDAS_URL, link["href"].strip()
                        )
                        break
                if not agenda_url:
                    continue
                date = self._date(label, section_year, agenda_url)
                if date is None:
                    self.logger.warning(f"No date for agenda item {label!r}")
                    continue
                found.setdefault(date, (_meeting_type(label, agenda_url), agenda_url))
        return found

    def _minutes(self, html: str) -> dict[datetime.date, tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one(".node__content") or soup
        candidates: dict[datetime.date, list[tuple[bool, str, str]]] = {}
        year: Optional[int] = None
        # Walk the page in order: the current year is an <h2>, earlier years
        # are accordion items titled with the bare year.
        for element in body.find_all(True):
            classes = " ".join(element.get("class") or [])
            if element.name == "h2" or "field--name-field-title" in classes:
                match = _YEAR_ONLY.match(element.get_text(" ", strip=True))
                if match:
                    year = int(match.group(1))
                continue
            if element.name != "a" or not element.get("href") or year is None:
                continue
            href = element["href"].strip()
            if "/sites/default/files/" not in href or not href.lower().endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if "meeting" not in label.lower():
                continue
            url = urllib.parse.urljoin(_MINUTES_URL, href)
            date = self._date(label, year, url)
            if date is None:
                self.logger.warning(f"No date for minutes link {label!r}")
                continue
            confirmed = bool(_CONFIRMED.search(_filename(url)))
            candidates.setdefault(date, []).append(
                (confirmed, _meeting_type(label), url)
            )

        found = {}
        for date, options in candidates.items():
            # Confirmed minutes replace the unconfirmed copy when both are up.
            options.sort(key=lambda option: not option[0])
            found[date] = (options[0][1], options[0][2])
        return found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Either page failing raises: half a join would quietly drop every
        # agenda or every set of minutes.
        agendas = self._agendas(self.fetcher.fetch_with_requests(_AGENDAS_URL))
        minutes = self._minutes(self.fetcher.fetch_with_requests(_MINUTES_URL))
        if not minutes:
            # The minutes page carries the whole history back to 2021, so an
            # empty read means its year headings or links have changed, not
            # that there are no minutes. Without this every meeting would
            # come out agenda-only and look fine.
            raise RuntimeError(
                f"{_MINUTES_URL} yielded no minutes; the page markup has changed"
            )

        results = []
        for date in sorted(set(agendas) | set(minutes)):
            if date.year not in wanted:
                continue
            agenda_name, agenda_url = agendas.get(date, (None, None))
            minutes_name, minutes_url = minutes.get(date, (None, None))
            results.append(
                ScraperReturn(
                    name=agenda_name or minutes_name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_AGENDAS_URL if agenda_url else _MINUTES_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            message = (
                f"{self.council_name}: no meetings with papers in {sorted(wanted)}"
            )
            if clock.today() - datetime.date(min(wanted), 1, 1) > datetime.timedelta(
                days=90
            ):
                raise RuntimeError(message + "; the page markup has probably changed")
            self.logger.warning(message)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
