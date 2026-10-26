"""Meeting archives built by Ionata, a Hobart web agency, for Tasmanian councils.

Clarence, Glenorchy and Sorell run different themes from the same build: a
WordPress archive of meeting cards filtered by a GET form (`f_year`,
`f_month`, `f_cat`), newest-first, paged as `/page/N/?f_year=Y` with a
`a.next` link when there is a further page. Each card carries the meeting's
title, a "DD Month YYYY - h:mmpm" line, usually a location, and direct links
to its documents labelled "Agenda" and "Minutes" (alongside "Livestream",
"Attachments" and the odd "Audio", which are neither).

Only the markup differs, so a subclass supplies the listing URL, the CSS
selectors for the card and its fields, and how to name a meeting.

`f_year` is honoured server-side on all three, which is what makes the
production fetch cheap: one filtered year is one to four pages, not the whole
archive. Kingborough is also an Ionata site but on an older theme that ignores
`f_year`, so it is a scraper of its own.
"""

from __future__ import annotations

import datetime
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn
from aus_council_scrapers.constants import EARLIEST_YEAR

# The date and time are one string, separated by a hyphen on Clarence and
# Sorell and an em dash on Glenorchy.
_DATE_TIME_SEPARATOR = re.compile(r"\s+[-–—]\s+")

# A card with no real start time shows midnight: the field defaults to 00:00
# when the council leaves it blank, and no council meets at 12am.
_PLACEHOLDER_TIME = re.compile(r"^12:00\s*am$", re.IGNORECASE)

_AGENDA_LABEL = re.compile(r"^\s*agenda\s*$", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"^\s*minutes\s*$", re.IGNORECASE)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
# "12 October 2026", "10th October 2021", "8-December-2025", and the odd
# American "May 27 2024" in a Clarence title.
_DAY_MONTH_YEAR = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+({_MONTHS})[\s,-]+(\d{{4}})(?!\d)",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTHS})[\s-]+(\d{{1,2}})(?:st|nd|rd|th)?,?[\s-]+(\d{{4}})(?!\d)",
    re.IGNORECASE,
)
# Filename-only forms: "2026-09-28-Open-Council-Meeting-Agenda.pdf",
# Glenorchy's re-uploaded "OC_21062021_AGN.pdf", and "a07.02.22.pdf" /
# "Confirmed-GPA-Minutes-8.12.2025.pdf".
_ISO_DATE = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_COMPACT_DATE = re.compile(r"(?<![\d.])(\d\d)(\d\d)(20\d\d)(?![\d.])")
_NUMERIC_DATE = re.compile(r"(?<![\d.])(\d{1,2})[._-](\d{1,2})[._-](20\d\d|\d\d)(?!\d)")


def _date_or_none(year: int, month: int, day: int) -> Optional[datetime.date]:
    if year < 100:
        year += 2000
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def text_date(text: str) -> Optional[datetime.date]:
    """A date written out with its month name, as titles and some files do."""
    if m := _DAY_MONTH_YEAR.search(text):
        day, month, year = m.groups()
    elif m := _MONTH_DAY_YEAR.search(text):
        month, day, year = m.groups()
    else:
        return None
    month_number = _MONTHS.split("|").index(month.lower()) + 1
    return _date_or_none(int(year), month_number, int(day))


def filename_date(url: str) -> Optional[datetime.date]:
    """The meeting date a document's filename claims, if it claims one."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    if found := text_date(name):
        return found
    if m := _ISO_DATE.search(name):
        year, month, day = m.groups()
    elif m := (_COMPACT_DATE.search(name) or _NUMERIC_DATE.search(name)):
        day, month, year = m.groups()
    else:
        return None
    return _date_or_none(int(year), int(month), int(day))


def reconcile_date(
    listed: datetime.date,
    title: Optional[datetime.date],
    documents: dict[str, Optional[datetime.date]],
) -> tuple[datetime.date, dict[str, datetime.date]]:
    """The meeting's date, and the documents whose filenames dispute it.

    The card's date field is typed separately from its title and from the
    filenames, and on Glenorchy it is wrong more often than either: a
    Planning Authority card dated 18 March 2024 is titled 11 November 2024
    and links PA_04112024_AGN.pdf, and "Council Meeting – 21 June 2021" is
    dated 28 June, the night of the next meeting, which has its own card.
    Clarence and Sorell each have one card a day off its title and files.

    So each source gets a vote—the field, the title, each dated filename—
    and the date most of them name wins, the field winning a tie.

    A document outvoted at least two to one is returned as disputed, with the
    date it names. That alone does not make it another meeting's: Clarence's
    23 January 2023 agenda is a16.01.23.pdf because it is the agenda of the
    16 January meeting, adjourned to the 23rd. The caller decides, by checking
    whether a meeting on the named date exists. A lone disagreement (one
    source against one) is never disputed, since it cannot say which side is
    wrong.
    """
    votes = [listed] + [d for d in (title, *documents.values()) if d is not None]
    counts = {d: votes.count(d) for d in votes}
    best = max(counts.values())
    chosen = listed if counts[listed] == best else next(d for d in votes if counts[d] == best)
    disputed = {
        kind: named
        for kind, named in documents.items()
        if named is not None
        and named != chosen
        and counts[chosen] >= 2 * counts[named]
    }
    return chosen, disputed


class IonataMeetingsScraper(BaseScraper):
    # The archive page carrying the f_year filter form.
    listing_url: str
    # One meeting.
    card_selector: str
    title_selector: str
    # The "DD Month YYYY - h:mmpm" element and the location, both relative to
    # the card. The location is optional on the page, not just here.
    date_selector: str
    location_selector: Optional[str] = None

    def _wanted_years(self) -> list[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return sorted(years_filter)
        return list(range(EARLIEST_YEAR, clock.current_year() + 3))

    def meeting_name(self, card: Tag, title: str, documents: list[str]) -> str:
        """The meeting type. Subclasses normalise their council's titles.

        `documents` is the card's agenda and minutes URLs. A filename is
        sometimes a better witness to the meeting type than the card: Clarence
        titles a special meeting "Clarence City Council Meeting – 10 June 2025"
        and links Special-Council-Meeting-Agenda-10-June-2025.pdf.
        """
        raise NotImplementedError

    def document_url(self, href: str, kind: str) -> Optional[str]:
        """A link the card labels Agenda or Minutes, as a URL worth storing.

        `kind` is "agenda" or "minutes", the card's label for the link, for
        a subclass whose link can lead to a folder holding both.

        Hrefs are hand-pasted, and a trailing space survives as `%20`—Sorell
        has one, and the asset host 403s it. Anything not ending in `.pdf` is
        refused by default: a council that links a viewer page instead of the
        document is not giving us the document.
        """
        href = re.sub(r"(%20|\s)+$", "", href.strip())
        url = urljoin(self.listing_url, href)
        if not urlparse(url).path.lower().endswith(".pdf"):
            return None
        return url

    def _parse_card(
        self, card: Tag, year: int
    ) -> Optional[tuple[ScraperReturn, dict[str, datetime.date]]]:
        title_el = card.select_one(self.title_selector)
        date_el = card.select_one(self.date_selector)
        if title_el is None or date_el is None:
            self.logger.warning(
                f"{self.council_name}: meeting card without a title or date, skipped"
            )
            return None
        title = " ".join(title_el.get_text(" ", strip=True).split())
        date_text = " ".join(date_el.get_text(" ", strip=True).split())

        date_part, *time_part = _DATE_TIME_SEPARATOR.split(date_text, maxsplit=1)
        try:
            meeting_date = parse_date(date_part, dayfirst=True).date()
        except (ValueError, OverflowError):
            self.logger.warning(
                f"{self.council_name}: unparseable date {date_text!r} on {title!r}"
            )
            return None
        if meeting_date.year != year:
            # The listing was asked for one year. A card from another means the
            # filter stopped being honoured, and every year would then fetch
            # the whole archive—say so rather than paying for it quietly.
            self.logger.warning(
                f"{self.council_name}: f_year={year} returned a {meeting_date.year} "
                f"meeting ({title!r}); the year filter may have stopped working"
            )
            return None
        time = time_part[0].strip() if time_part else None
        if time and _PLACEHOLDER_TIME.match(time):
            time = None

        location = None
        if self.location_selector:
            location_el = card.select_one(self.location_selector)
            if location_el is not None:
                location = " ".join(location_el.get_text(" ", strip=True).split())
                location = location or None

        agenda_url = minutes_url = None
        for link in card.select("a[href]"):
            label = link.get_text(" ", strip=True)
            if _AGENDA_LABEL.match(label):
                kind = "agenda"
            elif _MINUTES_LABEL.match(label):
                kind = "minutes"
            else:
                # Livestream, Attachments, Audio—and on Clarence the
                # quarterly report or annual plan tabled at that meeting.
                continue
            url = self.document_url(link["href"], kind)
            if url is None:
                self.logger.info(
                    f"{self.council_name}: {title!r} links its {kind} to "
                    f"{link['href']}, which is not a direct document; left out"
                )
                continue
            if kind == "agenda" and agenda_url is None:
                agenda_url = url
            elif kind == "minutes" and minutes_url is None:
                minutes_url = url

        documents = {
            kind: filename_date(url)
            for kind, url in (("agenda", agenda_url), ("minutes", minutes_url))
            if url
        }
        listed_date = meeting_date
        meeting_date, disputed = reconcile_date(listed_date, text_date(title), documents)
        if meeting_date != listed_date:
            self.logger.info(
                f"{self.council_name}: {title!r} is listed for {listed_date}; "
                f"its title and documents say {meeting_date}"
            )

        if not agenda_url and not minutes_url:
            return None

        record = ScraperReturn(
            name=self.meeting_name(
                card, title, [u for u in (agenda_url, minutes_url) if u]
            ),
            date=meeting_date.isoformat(),
            time=time,
            webpage_url=f"{self.listing_url}?f_year={year}",
            location=location,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )
        return record, disputed

    def _drop_misfiled(self, parsed: list[tuple]) -> list[ScraperReturn]:
        """Remove documents that belong to another meeting in the same year.

        A disputed document (see `reconcile_date`) is only taken off its card
        when the listing has a meeting on the date its filename names—then
        it is that meeting's, and leaving it here would put one agenda on two
        meetings, as Clarence's 9 June 2020 card does with the 29 June agenda.
        Without such a meeting it is most likely this meeting's under an old
        name, like an adjourned meeting's agenda, and is kept.
        """
        dates = {record.date for record, _ in parsed}
        kept = []
        for record, disputed in parsed:
            for kind, named in disputed.items():
                if named.isoformat() not in dates:
                    continue
                self.logger.warning(
                    f"{self.council_name}: the {kind} on the {record.name} of "
                    f"{record.date} is the {named} meeting's; left out"
                )
                setattr(record, f"{kind}_url", None)
            if not record.agenda_url and not record.minutes_url:
                continue
            record.download_url = record.agenda_url or record.minutes_url
            kept.append(record)
        return kept

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        results: list[ScraperReturn] = []

        for year in self._wanted_years():
            # A year with nothing published (one not yet reached, or before the
            # archive starts) returns the page with no cards, so it costs one
            # request and needs no special case.
            url: Optional[str] = f"{self.listing_url}?f_year={year}"
            seen_pages: set[str] = set()
            parsed: list[tuple] = []
            while url and url not in seen_pages:
                seen_pages.add(url)
                soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
                for card in soup.select(self.card_selector):
                    found = self._parse_card(card, year)
                    if found is not None:
                        parsed.append(found)
                next_link = soup.select_one("a.next[href]")
                url = urljoin(url, next_link["href"]) if next_link else None
            results.extend(self._drop_misfiled(parsed))

        if not results:
            self.logger.warning(
                f"{self.council_name}: no meetings with documents found at "
                f"{self.listing_url} for {self._wanted_years()}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
