import datetime
import html
import json
import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.alyka import PageTypeListingScraper, find_date, find_month
from aus_council_scrapers.base import ScraperReturn, register_scraper

_BASE_URL = "https://www.harvey.wa.gov.au"
# A WordPress build by Alyka that carries the page-type listing over from
# their Kentico sites: `div#pageTypeListing[data-api]` names a WP REST route
# (/wp-json/aw/v1/document) that answers PageTypeListingScraper's POST
# unchanged. One row per document, filtered to the "agendasminutes"
# publication type and one year, so a year is one POST.
#
# robots.txt disallows only /wp-admin/, /media_category, /tag and /category.
_LISTING_URL = f"{_BASE_URL}/documents-and-forms/"
_DATES_URL = f"{_BASE_URL}/shire/council/agendas-minutes-and-meeting-dates"
# The shire's news posts, through WordPress's own REST route. Special
# meetings are announced there as public notices ("Special Council Meeting
# June 2026": "... will be holding a Special Council Meeting ... on Tuesday,
# 9 June 2026 commencing at 4pm"), which is the only place outside the PDFs
# that a special meeting's day is written. One search returns every such
# notice back to 2022 (about 20 posts); `_fields` keeps it small.
_NOTICES_URL = (
    f"{_BASE_URL}/wp-json/wp/v2/posts?search=special%20council%20meeting"
    "&per_page=100&_fields=date,title,content"
)

# The listing names most papers by month only: "Ordinary Council Meeting
# Agenda September 2026", "Ordinary Council Meeting Confirmed Minutes August
# 2026". The filename says no more, and the row's release date is when the
# file was uploaded, not when the council met. What gives the day is the
# council's meeting-dates page, a table of the current schedule (November
# 2025 to October 2026 when this was written) with a column for Ordinary
# Council. So:
#
# - a title with a full date is dated by it (Special Council Meetings mostly
#   are: "Special Council Meeting Agenda 24 October 2023");
# - a month-only Ordinary Council title is dated by the schedule's Ordinary
#   Council entry for that month;
# - a month-only Special Council title is dated by the shire's public
#   notice of that meeting, when exactly one notice falls in the month and
#   was not later cancelled (12 May 2026's was);
# - a month-only title otherwise joins the one meeting of its kind that
#   another paper dates in that month (25 February 2025's agenda is titled
#   with its day and its minutes are not);
# - anything else is left out and logged, never given an invented day.
#
# The day is on every paper's cover ("Tuesday, 26 May 2026"), but reading
# it needs the PDF's bytes, which the fetcher does not return (it returns
# decoded text) and the cassettes do not store. Until the project decides
# to add that, two gaps remain. Earlier years keep only their titled and
# notified dates: most ordinary meetings before November 2025 are left out.
# And the schedule rolls forward: once the dates page moves on to the next
# council year (from about November), the current year's earlier ordinary
# meetings can no longer be dated, so a run late in the year returns fewer
# of them. The schedule's first and last months are logged on every run so
# that shift shows up.
_COUNCIL = re.compile(r"\bcouncil\b", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
# Not meetings of the council, or not the paper itself: the agenda briefing
# session (a councillor workshop held the week before), attachments,
# addenda, late items and additional attachments, and the electors' meeting
# (titled by year only).
_NOT_A_PAPER = re.compile(
    r"briefing|attachment|addendum|late item|electors|councillor", re.IGNORECASE
)
_NOTICE = re.compile(
    r"will be (?:holding|held)|has been scheduled|scheduled to be held", re.IGNORECASE
)
_CANCELLED = re.compile(r"\bcancel", re.IGNORECASE)
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\b"
)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)


@register_scraper
class HarveyScraper(PageTypeListingScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("harvey", "WA", _BASE_URL)

    def _ordinary_dates(self) -> dict[tuple[int, int], datetime.date]:
        """``(year, month) -> date`` from the schedule's Ordinary Council column."""
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_DATES_URL), "html.parser"
        )
        dates: dict[tuple[int, int], datetime.date] = {}
        for table in soup.find_all("table"):
            headers = [
                th.get_text(" ", strip=True).lower() for th in table.find_all("th")
            ]
            column = next(
                (i for i, h in enumerate(headers) if "ordinary council" in h), None
            )
            if column is None:
                continue
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) <= column:
                    continue
                found = find_date(cells[column].get_text(" ", strip=True))
                if found:
                    dates[(found[0].year, found[0].month)] = found[0]
        if not dates:
            self.logger.warning(
                "Harvey: the meeting-dates page has no Ordinary Council column; "
                "month-only meetings cannot be dated"
            )
        else:
            self.logger.info(
                f"Harvey: the meeting-dates page dates ordinary meetings from "
                f"{min(dates.values()):%B %Y} to {max(dates.values()):%B %Y}"
            )
        return dates

    def _special_notice_dates(self) -> dict[tuple[int, int], set[datetime.date]]:
        """``(year, month) -> dates`` that notices give for special meetings.

        Only a notice that a meeting will be held counts: "Special Council
        Meeting outcome" posts report a meeting after the fact and leave the
        year off. A cancellation notice takes its date back out. The first
        full date in a notice is the meeting's; later ones are when the
        agenda will be published or when submissions close.
        """
        posts = json.loads(self.fetcher.fetch_with_requests(_NOTICES_URL))
        notified: dict[tuple[int, int], set[datetime.date]] = {}
        cancelled: set[datetime.date] = set()
        for post in posts:
            title = html.unescape((post.get("title") or {}).get("rendered") or "")
            if not _SPECIAL.search(title) or not _COUNCIL.search(title):
                continue
            text = html.unescape(
                re.sub(
                    r"\s+",
                    " ",
                    BeautifulSoup(
                        (post.get("content") or {}).get("rendered") or "",
                        "html.parser",
                    ).get_text(" "),
                )
            )
            date = self._notice_date(text, post.get("date") or "")
            if date is None:
                continue
            if _CANCELLED.search(title) or _CANCELLED.search(text):
                cancelled.add(date)
            elif _NOTICE.search(text):
                notified.setdefault((date.year, date.month), set()).add(date)
        return {
            month: dates - cancelled
            for month, dates in notified.items()
            if dates - cancelled
        }

    def _rows(self, fragment: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(fragment, "html.parser")
        rows = []
        for item in soup.select("div.document-item"):
            if "document-item-head" in (item.get("class") or []):
                continue
            link = item.find("a", href=True)
            if link:
                rows.append(
                    (re.sub(r"\s+", " ", link.get_text(" ", strip=True)), link["href"])
                )
        return rows

    def _date(
        self, title: str, special: bool, ordinary_dates
    ) -> Optional[datetime.date]:
        found = find_date(title)
        if found:
            return found[0]
        month = find_month(title)
        if month and not special:
            return ordinary_dates.get(month)
        return None

    @staticmethod
    def _notice_date(text: str, posted: str) -> Optional[datetime.date]:
        """The meeting date a notice gives.

        Usually in full. One notice (July 2025's) gives only "15 July"; the
        year is then the one that puts the meeting on or after the day the
        notice was posted, since a notice announces a meeting to come.
        """
        found = find_date(text)
        if found:
            return found[0]
        match = _DAY_MONTH.search(text)
        if not match or not posted:
            return None
        posted_on = datetime.date.fromisoformat(posted[:10])
        for year in (posted_on.year, posted_on.year + 1):
            try:
                date = parse_date(
                    f"{match.group(1)} {match.group(2)} {year}", dayfirst=True
                ).date()
            except (ValueError, OverflowError):
                return None
            if date >= posted_on:
                return date
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()
        config = self._listing_config(self._listing_page())
        offered = set(self.checkbox_values(config, "year"))
        ordinary_dates = self._ordinary_dates()
        special_dates = self._special_notice_dates()

        def fetch(year):
            fragment = self._search(
                config, {"publication-type": ["agendasminutes"], "year": [str(year)]}
            )
            rows = self._rows(fragment)
            self._warn_if_full(len(rows), f"{year}")
            return rows

        years = sorted(y for y in wanted if str(y) in offered)
        papers: dict[tuple[str, datetime.date], dict] = {}
        month_only: list[tuple[str, tuple[int, int], str, str, str]] = []
        for _, rows in self._each_year(years, fetch):
            for title, href in rows:
                if not _COUNCIL.search(title) or _NOT_A_PAPER.search(title):
                    continue
                if _MINUTES.search(title):
                    kind = "minutes"
                elif _AGENDA.search(title):
                    kind = "agenda"
                else:
                    continue
                special = bool(_SPECIAL.search(title))
                name = (
                    "Special Council Meeting" if special else "Ordinary Council Meeting"
                )
                date = self._date(title, special, ordinary_dates)
                if date is None:
                    month = find_month(title)
                    if month:
                        month_only.append((name, month, kind, href, title))
                    else:
                        self.logger.warning(
                            f"Harvey: {title!r} names no date; left out"
                        )
                    continue
                meeting = papers.setdefault(
                    (name, date), {"agenda": None, "minutes": None}
                )
                if meeting[kind] is None:
                    meeting[kind] = href

        undated = []
        for name, (year, month), kind, href, title in month_only:
            # The dates this meeting could be: those another paper of its
            # kind gives in the month, and for a special meeting, those its
            # notices give. Only one is a match; two is a guess.
            candidates = {
                key[1]
                for key in papers
                if key[0] == name and (key[1].year, key[1].month) == (year, month)
            }
            if name == "Special Council Meeting":
                candidates |= special_dates.get((year, month), set())
            if len(candidates) == 1:
                meeting = papers.setdefault(
                    (name, candidates.pop()), {"agenda": None, "minutes": None}
                )
                if meeting[kind] is None:
                    meeting[kind] = href
            else:
                undated.append(title)
        if undated:
            self.logger.warning(
                f"Harvey: {len(undated)} papers name only a month that neither "
                f"the meeting-dates page, a notice nor a dated sibling paper "
                f"gives one day for, and were left out: {undated[:5]}"
            )

        results = []
        for (name, date), docs in sorted(
            papers.items(), key=lambda kv: kv[0][1], reverse=True
        ):
            if date.year not in wanted:
                continue
            # No time: the dates page gives 4pm for the current schedule only.
            meeting = self._meeting(
                name, date, _LISTING_URL, docs["agenda"], docs["minutes"]
            )
            if meeting:
                results.append(meeting)
        self._log_result(results, f"{_LISTING_URL} for {years}")
        return results
