import datetime
import re
from collections import Counter
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_date, find_month
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://mtmarshall.wa.gov.au"
_MEETINGS = f"{_BASE_URL}/council-the-shire/council-meetings"
_LISTING_URL = f"{_MEETINGS}/minutes-and-agendas/"
_DATES_URL = f"{_MEETINGS}/meeting-dates-times/"

# One WordPress page lists every agenda and minutes since 2021, each a link
# to a Google Drive file ("Agenda – October 2026 Ordinary Council Meeting",
# "UNCONFIRMED Minutes – September 2026 Ordinary Meeting"). Ordinary meetings
# are named by month only, and nothing on the listing or in Drive's file
# names gives the day.
#
# A month is not a meeting date, so the day is taken from the council's
# meeting-dates page, which lists the current year's ordinary meetings
# ("20 October 2026 at 10:00am in Council Chambers, Bencubbin"), as
# Rockingham does. That leaves out every earlier year's ordinary meetings:
# the council meets on the third Tuesday, but a rule is not a record, and the
# agenda PDFs that would say are on Drive. Special and electors' meetings are
# kept when their label carries the full date ("Special Meeting of Council
# being held 31 July 2026"), in any year, since it is then the council's own
# statement of the day.
#
# The dates page is edited in place each year, not kept per year, so it can
# lag the papers: once it shows next year's dates (or still shows last
# year's), this year's ordinary papers have no day. For the current year, or
# any year past the page's, that fails the council rather than returning a
# quietly short list; for past years it is the documented gap.
#
# The dates page has its own slips: it is headed "dates in 2025" and lists
# "19 May 2025" among ten 2026 dates. 19 May 2025 was a Monday; 19 May 2026
# is a Tuesday like every other entry. An entry outside the year most of
# them share is moved into that year only when that leaves it on their
# weekday and its month is otherwise empty, and the move is logged.
#
# Each listing row also carries the document category it is filed under
# ("2026 Agendas"). That supplies a missing year ("Annual Electors Meeting
# being held on Tuesday, 10 February at 5:00pm", filed under 2026), and
# settles a label whose year is wrong: "Agenda – February 2025 Ordinary
# Meeting" appears twice, once under 2025 Agendas and once under 2026
# Agendas among the 2026 papers. A label whose year disagrees with its
# category is re-dated to the category's year only when another paper with
# the same label is filed under the label's own year; otherwise it is left
# out, since either could be the slip.
#
# Drive's /file/d/<id>/view is a viewer page; /uc?export=download&id=<id>
# serves the PDF (by a redirect to drive.usercontent.google.com). Neither is
# fetched here—Drive's robots.txt allows /file and disallows /uc, and
# drive.usercontent.google.com disallows everything—only emitted, as King
# Island emits its Drive papers. council-alerts downloads each emitted
# paper, so this is the same choice made there; Forbes and Carnamah, whose
# papers sit on the council's own disallowed paths, have no scraper. Two
# requests a night, both to the council's site, whose robots.txt disallows
# only /wp-admin/.

_DRIVE_ID = re.compile(r"drive\.google\.com/file/d/([\w-]+)")
_SCHEDULE_LINE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+at\s+(\d{1,2}(?:[:.]\d{2})?\s*[ap]m)\s+in\s+([^\n]+)",
    re.IGNORECASE,
)
_SKIP = re.compile(r"attachment|audio", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d\d)\b")
_CATEGORY_YEAR = re.compile(r"^(20\d\d)-")
_MONTH_NAME = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October"
    r"|November|December)\b",
    re.IGNORECASE,
)


def _category_year(link) -> Optional[int]:
    """The year of the document category the listing row is filed under."""
    row = link.find_parent("tr")
    if row is None:
        return None
    years = {
        int(match.group(1))
        for span in row.select("span[data-slug]")
        if (match := _CATEGORY_YEAR.match(span["data-slug"]))
    }
    return years.pop() if len(years) == 1 else None


def _meeting_type(label: str) -> str:
    if re.search(r"elector", label, re.IGNORECASE):
        return "Annual Electors Meeting"
    if re.search(r"special", label, re.IGNORECASE):
        return "Special Council Meeting"
    return "Ordinary Council Meeting"


@register_scraper
class MountMarshallScraper(BaseScraper):
    def __init__(self):
        super().__init__("mount_marshall", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _schedule(self) -> tuple[int, dict[tuple[int, int], tuple[datetime.date, str, str]]]:
        """The page's year, and ``{(year, month): (date, time, location)}``."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_DATES_URL), "html.parser")
        content = soup.select_one("main") or soup
        entries = []
        for match in _SCHEDULE_LINE.finditer(content.get_text("\n")):
            found = find_date(match.group(1))
            if found:
                entries.append(
                    (found[0], match.group(2).strip(), re.sub(r"\s+", " ", match.group(3)).strip())
                )
        if not entries:
            raise ValueError(f"{self.council_name}: no meeting dates on {_DATES_URL}")
        year = Counter(date.year for date, _, _ in entries).most_common(1)[0][0]
        weekday = Counter(date.weekday() for date, _, _ in entries).most_common(1)[0][0]
        held = Counter(date.month for date, _, _ in entries if date.year == year)
        schedule: dict[tuple[int, int], tuple] = {}
        clashes = set()
        for date, time, location in entries:
            if date.year != year:
                try:
                    moved = date.replace(year=year)
                except ValueError:
                    moved = None
                if moved is None or held[date.month] or moved.weekday() != weekday:
                    self.logger.warning(
                        f"{self.council_name}: dates page lists {date} among {year}; ignored"
                    )
                    continue
                self.logger.warning(
                    f"{self.council_name}: dates page lists {date} among {year}; read as {moved}"
                )
                date = moved
            key = (date.year, date.month)
            if key in schedule:
                clashes.add(key)
            schedule[key] = (date, time, location)
        for key in clashes:
            del schedule[key]
        return year, schedule

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Both pages are left to raise: without the listing there is nothing,
        # and without the dates no ordinary meeting can be dated.
        listing = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")
        schedule_year, schedule = self._schedule()

        papers = []
        for link in listing.find_all("a", href=True):
            match = _DRIVE_ID.search(link["href"])
            if not match:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if _SKIP.search(label):
                continue
            if _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                kind = "agenda"
            else:
                continue
            papers.append((kind, label, _category_year(link), match.group(1)))

        # Labels whose category does not contradict their year (filed under
        # it, or under no year), to tell a mistyped label from a misfiled one.
        consistent = {
            (kind, label)
            for kind, label, year, _ in papers
            if year is None or {int(y) for y in _YEAR.findall(label)} == {year}
        }

        meetings: dict[tuple, dict] = {}
        undated: Counter = Counter()
        for kind, label, category_year, drive_id in papers:
            label_years = {int(y) for y in _YEAR.findall(label)}
            if category_year and not label_years:
                label = _MONTH_NAME.sub(rf"\g<0> {category_year}", label, count=1)
            elif category_year and label_years != {category_year}:
                if (kind, label) in consistent:
                    fixed = _YEAR.sub(str(category_year), label)
                    self.logger.warning(
                        f"{self.council_name}: {label!r} is filed under {category_year}"
                        f" and another copy under its own year; read as {fixed!r}"
                    )
                    label = fixed
                else:
                    self.logger.warning(
                        f"{self.council_name}: {label!r} is filed under {category_year}; skipped"
                    )
                    continue

            name = _meeting_type(label)
            time = location = None
            found = find_date(label)
            month = find_month(label)
            if found:
                date = found[0]
            elif name == "Ordinary Council Meeting" and month:
                slot = schedule.get(month)
                if slot is None:
                    if month[0] not in wanted:
                        continue
                    if month[0] != schedule_year:
                        undated[month[0]] += 1
                    else:
                        self.logger.warning(
                            f"{self.council_name}: {label!r} has no date on the dates page; skipped"
                        )
                    continue
                date, time, location = slot
            else:
                if month and month[0] in wanted:
                    self.logger.warning(
                        f"{self.council_name}: {label!r} names the month only; skipped"
                    )
                continue
            if date.year not in wanted:
                continue

            url = f"https://drive.google.com/uc?export=download&id={drive_id}"
            meeting = meetings.setdefault(
                (date, name), {"time": time, "location": location}
            )
            unconfirmed = bool(_UNCONFIRMED.search(label))
            current = meeting.get(kind)
            # Confirmed minutes over the unconfirmed copy; otherwise the first
            # link, which is the newest upload.
            if current is None or (kind == "minutes" and current[1] and not unconfirmed):
                meeting[kind] = (url, unconfirmed)

        for year, count in sorted(undated.items()):
            message = (
                f"{self.council_name}: {count} ordinary-meeting papers for {year} cannot be"
                f" dated: the dates page lists {schedule_year}"
            )
            # The current year (and any later one) should be on the dates
            # page; if it is not, the page has moved on or not caught up, and
            # the night's run would otherwise drop every ordinary meeting.
            if year >= clock.current_year() or year > schedule_year:
                raise RuntimeError(message)
            self.logger.warning(message + " (past years are not dated)")

        results = []
        for (date, name), meeting in sorted(meetings.items()):
            agenda_url = meeting["agenda"][0] if "agenda" in meeting else None
            minutes_url = meeting["minutes"][0] if "minutes" in meeting else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=meeting["time"],
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                    location=meeting["location"],
                )
            )

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
