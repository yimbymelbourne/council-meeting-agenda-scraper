"""Wodonga City Council—DNN, one page of year accordions.

The Agendas and Minutes page holds every year the council keeps online as
an accordion item ("2026 past agendas and minutes", ..., "2017 past
minutes"). Each file is a ``div.lrg-btn``: its label in the ``aside``'s
``.col-10`` ("2026-02-23 Council meeting agenda") and its PDF on the sibling
``a``, whose own text is empty. Besides the agenda and minutes, a year
holds question-time responses, monthly information reports, attachment
parts and the odd item paper ("2023-05-15 Agenda item 7.3 - draft budget"),
none of which is a meeting's agenda or minutes.

**Robots.txt disallows ``/Portals/``**, where every PDF lives, for all user
agents. The listing page itself is allowed, and this scraper fetches only
that page: the document URLs are recorded, never requested (as with
``forbes`` in the national plan). So the PDFs were not fetched to check
them either.

**Dates.** From 2022 a label leads with an ISO date ("2026-05-25 council
meeting agenda", once "2023-6-26 Agenda"). Before that it is written out
("January 25, 2021 council minutes", "06 - June 29th, 2020 council meeting
minutes", "09 - 21st September council meeting minutes"), sometimes without
a year, which then comes from the accordion. Where a label's year disagrees
with its accordion's, the accordion wins: the 23 March 2026 papers are
labelled "2023-03-23", in the 2026 section, with "March_23__2026" in their
filenames. Much of 2020 is dated to the month only ("02 - February 2020
council meeting minutes", "12 - December council meeting minutes"). Such a
paper takes its day from another file of the same month only where that is
unambiguous (April 2020, from its question-time file); the rest are left
out rather than given an invented day.

Before 2022 the council published minutes only; agendas start in August
2022.

**Cost.** One request, about 470 KB, whatever years are wanted.

Cloudflare fronts the site (``server: cloudflare``); no challenge was seen
from a home IP. Not yet measured from a GitHub runner.
"""

import datetime
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.wodonga.vic.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/About-Council/Our-Council/Council-meetings/Agendas-and-minutes"
)

_SECTION_YEAR = re.compile(r"^\s*(\d{4})\b")
_ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|October"
    r"|November|December"
)
# "January 25, 2021", "June 28 2021", "June 29th, 2020", "December 6th, 2021".
_MONTH_DAY = re.compile(
    rf"\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE
)
# "7th September", "21st September".
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})\b(?:\s+(\d{{4}}))?", re.IGNORECASE
)
# A month alone: "04 - April 2020 ordinary meeting minutes".
_MONTH = re.compile(rf"\b(?:{_MONTHS})\b", re.IGNORECASE)

# The paper is named by the word "agenda" or "minutes" ("minutess" once).
# An item's paper or a supplementary file is not the meeting's agenda.
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes?s?\b", re.IGNORECASE)
_NOT_THE_PAPER = re.compile(
    r"\bitem\b|question|information report|attachments? part|tabled",
    re.IGNORECASE,
)
# A minutes file split in parts: the first part opens the minutes.
_LATER_PART = re.compile(r"\bpart\s+(?:two|three|2|3)\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


@register_scraper
class WodongaScraper(BaseScraper):
    def __init__(self):
        super().__init__("wodonga", "VIC", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _date(label: str, section_year: int) -> datetime.date | None:
        """The meeting date a label gives, or None when it gives only a month."""
        match = _ISO_DATE.match(label)
        if match:
            month, day = int(match.group(2)), int(match.group(3))
            return datetime.date(section_year, month, day)
        for pattern, month_group, day_group in (
            (_MONTH_DAY, 1, 2),
            (_DAY_MONTH, 2, 1),
        ):
            match = pattern.search(label)
            if match:
                stamp = f"{match.group(day_group)} {match.group(month_group)} {section_year}"
                return parse_date(stamp, dayfirst=True).date()
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        sections = soup.select("div.content--toggle--item")
        # Both checks guard against a markup change that would otherwise parse
        # to nothing and read as a council with no meetings.
        if not sections:
            raise RuntimeError(
                f"{self.council_name}: no year sections on {_LISTING_URL}"
            )
        if not soup.select("div.content--toggle--item div.lrg-btn"):
            raise RuntimeError(
                f"{self.council_name}: no lrg-btn file buttons on {_LISTING_URL}"
            )

        meetings: dict = {}
        # (label, kind, url, special, year, month) for papers dated to the
        # month only, and every day any file in the same month names.
        month_only: list[tuple] = []
        days_named: dict[tuple[int, int], set[datetime.date]] = {}
        for section in sections:
            # The section's own toggle link carries its title.
            title = section.find("a", recursive=False)
            title_text = title.get_text(" ", strip=True) if title else ""
            year_match = _SECTION_YEAR.match(title_text)
            if not year_match:
                continue
            section_year = int(year_match.group(1))
            if section_year not in wanted:
                continue

            for button in section.select("div.lrg-btn"):
                label_div = button.select_one(".col-10")
                anchor = button.find("a", href=True)
                if label_div is None or anchor is None or not anchor["href"].strip():
                    continue
                label = re.sub(r"\s+", " ", label_div.get_text(" ", strip=True))
                href = urljoin(_LISTING_URL, anchor["href"].strip())
                # Any file's label or filename may name the meeting's day
                # ("Question_time_council_meeting_of_20_April_2020-1.pdf").
                filename = href.rsplit("/", 1)[-1].replace("_", " ")
                for text in (label, filename):
                    try:
                        named = self._date(text, section_year)
                    except ValueError:
                        # A filename's digits that are not a real date; this
                        # is only a hint, so it is passed over.
                        continue
                    if named is not None:
                        days_named.setdefault((named.year, named.month), set()).add(
                            named
                        )
                if _NOT_THE_PAPER.search(label) or _LATER_PART.search(label):
                    continue
                if _MINUTES.search(label):
                    kind = "minutes"
                elif _AGENDA.search(label):
                    kind = "agenda"
                else:
                    continue
                date = self._date(label, section_year)
                if date is None:
                    month = _MONTH.search(label)
                    if month:
                        month_only.append(
                            (
                                label,
                                kind,
                                href,
                                bool(_SPECIAL.search(label)),
                                section_year,
                                parse_date(f"1 {month.group(0)} 2000").month,
                            )
                        )
                    continue
                # Keyed by date alone: Wodonga has never held two meetings on
                # one day here, and a special meeting's papers do not always
                # both say "special".
                meeting = meetings.setdefault(
                    date, {"agenda": None, "minutes": None, "special": False}
                )
                meeting["special"] |= bool(_SPECIAL.search(label))
                if meeting[kind] is None:
                    meeting[kind] = href

        # Much of 2020 is labelled by month alone ("04 - April 2020 ordinary
        # meeting minutes"). Such a paper takes a day only when another file
        # of that month names exactly one day that no dated paper already
        # holds: April 2020's question-time file is "..._of_20_April_2020",
        # and nothing else in April is dated. June 2020's special-meeting
        # minutes are left out, because the only June day named is the 29th,
        # which is the ordinary meeting's. A day is never guessed.
        left_out = []
        for label, kind, href, special, year, month in month_only:
            free = days_named.get((year, month), set()) - set(meetings)
            if len(free) != 1:
                left_out.append(label)
                continue
            date = free.pop()
            self.logger.info(
                f"{self.council_name}: {label!r} dated {date} from a sibling file"
            )
            meeting = meetings.setdefault(
                date, {"agenda": None, "minutes": None, "special": special}
            )
            if meeting[kind] is None:
                meeting[kind] = href
        if left_out:
            self.logger.info(
                f"{self.council_name}: {len(left_out)} paper(s) dated to the month "
                f"only, left out: {left_out}"
            )

        results = []
        for date, papers in sorted(meetings.items(), reverse=True):
            results.append(
                ScraperReturn(
                    name=(
                        "Special Council Meeting"
                        if papers["special"]
                        else "Council Meeting"
                    ),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=papers["agenda"],
                    minutes_url=papers["minutes"],
                    download_url=papers["agenda"] or papers["minutes"],
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
