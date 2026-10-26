import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = (
    "https://lockhart.nsw.gov.au/council/council-meetings/business-papers-and-minutes/"
)

# One WordPress page holds every year since 2022, a heading per year and under
# it a flat list of labelled links: "Business Paper - Ordinary Meeting - 19
# October 2026", "Unconfirmed Minutes - 21 September 2026", "Confirmed Minutes
# - Extraordinary Meeting - 9 October 2025", plus attachments, late reports
# and audio recordings, which are skipped. One request covers the whole
# history.
#
# "Minutes of the Tourism & Economic Development Steering Committee" is a
# committee's minutes attached to a business paper, so a minutes label must
# start with the word (or Confirmed/Unconfirmed) and a dash.
_AGENDA_LABEL = re.compile(r"^business paper\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^(?:(?:un)?confirmed\s+)?minutes\s*-", re.IGNORECASE)

_MONTHS = [
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
_FULL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_-]+(20\d{2})",
    re.IGNORECASE,
)
_MONTH_YEAR = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b",
    re.IGNORECASE,
)
_YYYYMMDD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def _dates(text: str) -> list[datetime.date]:
    found = []
    for day, month, year in _FULL_DATE.findall(text):
        try:
            found.append(
                datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
            )
        except ValueError:
            pass
    return found


def _file_dates(url: str) -> list[datetime.date]:
    name = unquote(url.rsplit("/", 1)[-1])
    found = _dates(name)
    for y, m, d in _YYYYMMDD.findall(name):
        try:
            found.append(datetime.date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return found


@register_scraper
class LockhartScraper(BaseScraper):
    def __init__(self):
        super().__init__("lockhart", "NSW", "https://lockhart.nsw.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _date_of(self, label: str, url: str) -> Optional[datetime.date]:
        """The meeting date, from the label, or the file name if the label
        gives only the month.

        The label wins when it has a whole date: the 21 October 2024 business
        paper is filed as "...-19-October-2024.pdf", a Saturday. Labels from
        2022 and 2023 give only "Business Paper - July 2023"; the file name
        then supplies the day, but only a date inside the labelled month is
        taken, so a stray date cannot move a meeting to another month.
        """
        in_label = _dates(label)
        if in_label:
            return in_label[0]
        month_year = _MONTH_YEAR.search(label)
        if not month_year:
            return None
        month = _MONTHS.index(month_year.group(1)[:3].lower()) + 1
        year = int(month_year.group(2))
        in_month = {d for d in _file_dates(url) if (d.year, d.month) == (year, month)}
        return in_month.pop() if len(in_month) == 1 else None

    def _place_undated(self, meetings, label, url, is_agenda, wanted) -> None:
        """Put a paper whose label and file name give only the month onto
        the one meeting of that month, if there is exactly one.

        "Business Paper - March 2023" and "Business Paper - July 2022" carry
        no day anywhere, but their months each hold a single meeting whose
        minutes are dated (20 March 2023, 18 July 2022). With two meetings in
        the month the paper could be either, so it is left out rather than
        guessed.
        """
        month_year = _MONTH_YEAR.search(label)
        if not month_year:
            self.logger.warning(f"{self.council_name}: no date for {label!r}; left out")
            return
        month = _MONTHS.index(month_year.group(1)[:3].lower()) + 1
        year = int(month_year.group(2))
        if year not in wanted:
            return
        same_month = [d for d in meetings if (d.year, d.month) == (year, month)]
        slot = "agenda" if is_agenda else "minutes"
        if len(same_month) == 1 and meetings[same_month[0]][slot] is None:
            meetings[same_month[0]][slot] = url
            return
        self.logger.warning(
            f"{self.council_name}: no day for {label!r} and {len(same_month)} "
            f"meetings that month; left out"
        )

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        meetings: dict[datetime.date, dict] = {}
        undated = []
        found_any = False
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            is_agenda = bool(_AGENDA_LABEL.match(label))
            is_minutes = bool(_MINUTES_LABEL.match(label))
            if not (is_agenda or is_minutes):
                continue
            url = urljoin(_LISTING_URL, link["href"].strip())
            name = unquote(url.rsplit("/", 1)[-1]).lower()
            if not name.endswith((".pdf", ".docx", ".doc")):
                continue
            found_any = True
            # The March 2022 "Business Paper" links the confirmed minutes.
            if is_agenda and "minutes" in name and "business" not in name:
                continue

            date = self._date_of(label, url)
            if date is None:
                undated.append((label, url, is_agenda))
                continue
            if date.year not in wanted:
                continue

            meeting = meetings.setdefault(
                date,
                {
                    "agenda": None,
                    "minutes": None,
                    "minutes_confirmed": False,
                    "extra": False,
                },
            )
            # The type is in the business paper's label, or only in a minutes
            # file name ("Confirmed-Minutes-Extraordinary-Meeting-24-June-2026").
            if "extraordinary" in label.lower() or "extraordinary" in name:
                meeting["extra"] = True
            if is_agenda:
                if meeting["agenda"] is None:
                    meeting["agenda"] = url
            else:
                confirmed = label.lower().startswith("confirmed")
                # Prefer confirmed minutes over unconfirmed ones if both are up.
                if meeting["minutes"] is None or (
                    confirmed and not meeting["minutes_confirmed"]
                ):
                    meeting["minutes"] = url
                    meeting["minutes_confirmed"] = confirmed

        if not found_any:
            raise ValueError(
                f"{self.council_name}: no business papers or minutes on {_LISTING_URL}"
            )
        for label, url, is_agenda in undated:
            self._place_undated(meetings, label, url, is_agenda, wanted)

        results = []
        for date in sorted(meetings, reverse=True):
            m = meetings[date]
            results.append(
                ScraperReturn(
                    name=(
                        "Extraordinary Council Meeting"
                        if m["extra"]
                        else "Ordinary Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=m["agenda"],
                    minutes_url=m["minutes"],
                    download_url=m["agenda"] or m["minutes"],
                )
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
