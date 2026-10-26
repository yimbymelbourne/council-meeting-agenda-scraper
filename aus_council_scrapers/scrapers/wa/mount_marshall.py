import datetime
import re
from collections import Counter
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import find_date, find_month
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.google_drive import download_url
from aus_council_scrapers.pdf_dates import (
    NotAPdf,
    PdfGone,
    PdfUnavailable,
    find_meeting_date,
)

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
# A month is not a meeting date, so for the current year the day is taken
# from the council's meeting-dates page, which lists that year's ordinary
# meetings ("20 October 2026 at 10:00am in Council Chambers, Bencubbin"), as
# Rockingham does. Special and electors' meetings are kept when their label
# carries the full date ("Special Meeting of Council being held 31 July
# 2026"), in any year, since it is then the council's own statement of the
# day.
#
# Earlier years are not on the dates page, so a month-only paper of a past
# year (any meeting type), or of a month the dates page leaves out, is dated
# from the first page of its own PDF (`pdf_dates`): "Notice is hereby given
# that an Ordinary Meeting of Council was held on Tuesday 20 June 2023". The
# minutes are read first, since they record the day the meeting was held,
# then the agenda; the first that gives a day in the label's month dates the
# meeting, and a meeting none dates is left out. Six sets of 2022-2023
# minutes are 10-63 MB with the cover nowhere in their first bytes and no
# agenda beside them; they were downloaded once and their covers read
# (`_CORRECTIONS`). Every date read this way was checked against the cover on
# 26 Oct 2026: where a meeting has both papers, the agenda and the minutes
# give the same day.
#
# The dates page is edited in place each year, not kept per year, so it can
# lag the papers: once it shows next year's dates (or still shows last
# year's), this year's ordinary papers have no day. For the current year, or
# any year past the page's, that fails the council rather than returning a
# quietly short list.
#
# The dates page has its own slips: it is headed "dates in 2025" and lists
# "19 May 2025" among ten 2026 dates. 19 May 2025 was a Monday; 19 May 2026
# is a Tuesday like every other entry. An entry outside the year most of
# them share is moved into that year only when that leaves it on their
# weekday and its month is otherwise empty, and the move is logged.
#
# Each listing row also carries the document category it is filed under
# ("2026 Agendas", "2024 Council Minutes"). That supplies a missing year
# ("Annual Electors Meeting being held on Tuesday, 10 February at 5:00pm",
# filed under 2026), and settles a label whose year is wrong: "Agenda –
# February 2025 Ordinary Meeting" appears twice, once under 2025 Agendas and
# once under 2026 Agendas among the 2026 papers (its cover reads 10 February
# 2026). A label whose year disagrees with its category is re-dated to the
# category's year only when another paper with the same label is filed under
# the label's own year; otherwise it is left out, since either could be the
# slip. The category also decides agenda or minutes: two papers filed under
# 2024 Agendas are labelled "Minutes – Ordinary Meeting April 2024" and
# "Minutes – Special Meeting January 2024", and both covers read "AGENDA".
#
# A documented robots.txt exception, widened on 26 Oct 2026. Drive's
# /file/d/<id>/view is a viewer page; /uc?export=download&id=<id> serves the
# PDF, by a 303 redirect to drive.usercontent.google.com/download (200,
# `application/octet-stream`, a `.pdf` attachment, no login; checked 26 Oct
# 2026; see `google_drive.py`). drive.google.com/robots.txt (checked 26 Oct 2026) allows a list of
# prefixes, `/file` among them, and ends
#
#     Disallow: /
#
# so /uc is disallowed; drive.usercontent.google.com/robots.txt is
# `User-agent: *` / `Disallow: /`. Papers are emitted as /uc links, as King
# Island's are, and council-alerts downloads each one. Since 26 Oct 2026 this
# scraper also fetches them itself, by the maintainer's decision that council
# papers on robots-disallowed hosts get the same documented exception: a
# month-only paper not dated by the dates page has its first 256 KB read
# through /uc (and the whole file, up to 8 MB, where those bytes give no
# day). A production run for 2026 reads none, since every 2026 ordinary
# meeting is on the dates page and its other meetings carry their dates in
# their labels; a current-year paper is read only when the dates page does
# not date it (a month-only special meeting, or a month the page leaves
# out), and the reads otherwise fall on runs for past years. A
# paper that needs a Google login (one set of minutes, Jan 2024) or answers
# 404 when read is left out. Nothing else on Drive is requested. Two requests
# a night, both to the council's site, whose robots.txt disallows only
# /wp-admin/.

_DRIVE_ID = re.compile(r"drive\.google\.com/file/d/([\w-]+)")

# Minutes with no agenda on the page, 10-63 MB, whose cover is not in their
# first 256 KB: too large to read on any run. Each was downloaded once (26
# Oct 2026) and its first page read; the quote is what the cover says.
_CORRECTIONS: dict[str, tuple[datetime.date, str]] = {
    # Minutes – Ordinary Meeting July 2022 (12 MB)
    "19hD8KhnSwMNlZNoaU78u2jR2GR1X81VY": (
        datetime.date(2022, 7, 19), "was held on Tuesday 19 July 2022"
    ),
    # Minutes – Ordinary Meeting August 2022 (13 MB)
    "1uQvR7EvionZdblf9KwoLFkiDkeyuutKV": (
        datetime.date(2022, 8, 16), "was held on Tuesday 16 August 2022"
    ),
    # Minutes – Ordinary Meeting September 2022 (32 MB)
    "1cb3Vvh4i7_HEacXaoR0T72axbooaGPAy": (
        datetime.date(2022, 9, 20), "was held on Tuesday 20 September 2022"
    ),
    # Minutes – Ordinary Meeting December 2022 (63 MB); a Monday
    "1fUcEMdFKRRI9BqVgf2xF2dsEC4SSmtIR": (
        datetime.date(2022, 12, 12), "was held on Monday 12 December 2022"
    ),
    # Minutes – Ordinary Meeting February 2023 (11 MB)
    "1Fa-OKzcpVaMOnWmdiiWLZMnKo59hwVwm": (
        datetime.date(2023, 2, 14), "was held on Tuesday 14 February 2023"
    ),
    # Minutes – Ordinary Meeting May 2023 (19 MB)
    "1DX9y5l1r8ZL6bcO-uIdFabgOye3Ani_k": (
        datetime.date(2023, 5, 16), "was held on Tuesday 16 May 2023"
    ),
}
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


def _category_kind(link) -> Optional[str]:
    """"agenda" or "minutes" from the categories the row is filed under."""
    row = link.find_parent("tr")
    if row is None:
        return None
    kinds = set()
    for span in row.select("span[data-slug]"):
        slug = span["data-slug"]
        if "agenda" in slug:
            kinds.add("agenda")
        elif "minutes" in slug:
            kinds.add("minutes")
    return kinds.pop() if len(kinds) == 1 else None


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

    def _date_from_papers(
        self, papers: list[tuple[str, str, bool]], year: int, month: int
    ) -> tuple[Optional[datetime.date], set[str]]:
        """The day a month-only meeting's own papers give, and the papers
        that cannot be emitted (gone, or not a PDF without a login).

        Minutes first, confirmed before unconfirmed, then agendas; each in
        listing order, newest upload first. The first paper that gives a day
        in the label's month dates the meeting, and the rest are not read.
        """
        order = sorted(
            range(len(papers)),
            key=lambda i: (papers[i][0] != "minutes", papers[i][2], i),
        )
        unusable: set[str] = set()
        for i in order:
            _, drive_id, _ = papers[i]
            if drive_id in _CORRECTIONS:
                date, _ = _CORRECTIONS[drive_id]
                if (date.year, date.month) == (year, month):
                    return date, unusable
                continue
            url = download_url(drive_id)
            try:
                found = self.fetcher.fetch_pdf_text(url)
                date = find_meeting_date(found.text, year, month)
                if date is None and not found.complete:
                    found = self.fetcher.fetch_pdf_text(url, partial=False)
                    date = find_meeting_date(found.text, year, month)
            except (PdfGone, NotAPdf) as e:
                # A dead link, or a file Drive serves only after a login.
                self.logger.warning(f"{self.council_name}: {e}; left out")
                unusable.add(drive_id)
                continue
            except PdfUnavailable as e:
                self.logger.info(f"{self.council_name}: cannot read {url}: {e}")
                continue
            if date is not None:
                return date, unusable
            start = re.sub(r"\s+", " ", found.text)[:160]
            self.logger.info(
                f"{self.council_name}: {url} gives no single day in "
                f"{year}-{month:02d}: {start!r}"
            )
        return None, unusable

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        this_year = clock.current_year()

        # Both pages are left to raise: without the listing there is nothing,
        # and without the dates no ordinary meeting of this year can be dated.
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
                kind = None
            filed_as = _category_kind(link)
            if filed_as and kind and filed_as != kind:
                self.logger.info(
                    f"{self.council_name}: {label!r} is filed under {filed_as}; read as {filed_as}"
                )
            kind = filed_as or kind
            if kind is None:
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

        def add(date, name, kind, drive_id, unconfirmed, time=None, location=None):
            meeting = meetings.setdefault(
                (date, name), {"time": time, "location": location}
            )
            current = meeting.get(kind)
            # Confirmed minutes over the unconfirmed copy; otherwise the first
            # link, which is the newest upload.
            if current is None or (kind == "minutes" and current[1] and not unconfirmed):
                meeting[kind] = (download_url(drive_id), unconfirmed)

        undated: Counter = Counter()
        # Month-only papers to be dated from their PDFs, by (year, month, name).
        pending: dict[tuple[int, int, str], list[tuple[str, str, bool]]] = {}
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
            unconfirmed = bool(_UNCONFIRMED.search(label))
            found = find_date(label)
            month = find_month(label)
            if found:
                if found[0].year in wanted:
                    add(found[0], name, kind, drive_id, unconfirmed)
                continue
            if not month or month[0] not in wanted:
                continue
            slot = schedule.get(month) if name == "Ordinary Council Meeting" else None
            if slot is not None:
                date, time, location = slot
                add(date, name, kind, drive_id, unconfirmed, time, location)
            elif (
                name == "Ordinary Council Meeting"
                and month[0] != schedule_year
                and (month[0] >= this_year or month[0] > schedule_year)
            ):
                # This year's ordinary meetings belong on the dates page.
                undated[month[0]] += 1
            else:
                pending.setdefault((*month, name), []).append((kind, drive_id, unconfirmed))

        for year, count in sorted(undated.items()):
            # The current year (and any later one) should be on the dates
            # page; if it is not, the page has moved on or not caught up, and
            # the night's run would otherwise drop every ordinary meeting.
            raise RuntimeError(
                f"{self.council_name}: {count} ordinary-meeting papers for {year} cannot be"
                f" dated: the dates page lists {schedule_year}"
            )

        left_out = []
        for (year, month, name), group in sorted(pending.items()):
            date, unusable = self._date_from_papers(group, year, month)
            usable = [paper for paper in group if paper[1] not in unusable]
            if date is None or not usable:
                left_out.append(f"{name} {year}-{month:02d}")
                continue
            for kind, drive_id, unconfirmed in usable:
                add(date, name, kind, drive_id, unconfirmed)
        if left_out:
            self.logger.warning(
                f"{self.council_name}: left out, no day on the dates page or in the PDFs: {left_out}"
            )

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
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
