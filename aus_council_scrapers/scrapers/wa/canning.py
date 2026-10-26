import datetime
import json
import re
from typing import Optional

from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = "https://www.canning.wa.gov.au/agendas-and-minutes/"
_SEARCH_URL = "https://www.canning.wa.gov.au/api/agendas-minutes/search"

# The listing page is a Preact app over this Umbraco search endpoint, and the
# page id is the `data-pageId` on its root element. The app never sends a page
# size, so it gets 12 results a page; `PageSize` is honoured (`ItemsPerPage`,
# the name the response uses, is ignored), which makes the whole archive—
# 602 documents back to January 2019—a single request.
_PAGE_ID = "1196"
_PAGE_SIZE = 1000

# Each result is one document, not one meeting, named
# "<Meeting type> - <date> - <document>", e.g.
# "Ordinary Council Meeting - 20 October 2026 - Agenda". A few put the parts in
# another order ("Minutes - Audit and Risk Committee - 6 March 2025"), and one
# drops the space after the hyphen ("- 11 May 2021 -Agenda"). Splitting on a
# hyphen with whitespace on at least one side keeps report numbers such as
# "CC-074-20" in one piece.
_PART_SEPARATOR = re.compile(r"\s+-\s*|\s*-\s+")
_DATE = re.compile(
    r"\b(\d{1,2})(?:\s*&\s*\d{1,2})?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{4})\b",
    re.IGNORECASE,
)

# Only these labels are the meeting's own agenda or minutes. Everything else
# Canning files alongside them—"Large Attachments", "Late Items Agenda",
# "Attachments to Reports", presentations, single late reports—is either a
# supplement to the agenda or not an agenda at all.
_AGENDA_LABEL = re.compile(r"^agenda$", re.IGNORECASE)
_MINUTES_LABELS = {
    # Best first: confirmed minutes supersede the unconfirmed draft when a
    # meeting has both (Audit and Risk, 28 August 2019, has "Minutes" and
    # "Confirmed Minutes").
    "confirmed minutes": 0,
    "minutes": 1,
    "unconfirmed minutes": 2,
}

# Special Council, 22 October 2019, was two meetings, and the second one's
# documents are labelled "Second Meeting Agenda" / "Second Meeting Confirmed
# Minutes".
_SECOND_MEETING = re.compile(r"^second meeting\s+", re.IGNORECASE)

# The search filters on `displayDate`, which is when a document was listed,
# not when the meeting was held: seven of the 602 are dated up to a week
# before their meeting. Widening the requested window by a month either side
# keeps a January meeting whose agenda went up in December, and the meeting
# date read from the title then decides which year it belongs to.
_LISTING_SLACK = datetime.timedelta(days=31)


@register_scraper
class CanningScraper(BaseScraper):
    def __init__(self):
        super().__init__("canning", "WA", "https://www.canning.wa.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _search(self, date_from: datetime.date, date_to: datetime.date) -> list:
        items = []
        page = 1
        while True:
            payload = {
                "CurrentPageId": _PAGE_ID,
                "SortBy": "DateDesc",
                "Page": page,
                "PageSize": _PAGE_SIZE,
                "Term": "",
                "CategoryTagIds": [],
                "TimePeriod": "CustomRange",
                "DateFrom": date_from.isoformat(),
                "DateTo": date_to.isoformat(),
            }
            body = json.loads(
                self.fetcher.fetch_with_requests(
                    _SEARCH_URL, method="POST", json=payload
                )
            )
            items.extend(body.get("items") or [])
            if not body.get("hasNextPage"):
                return items
            page += 1

    @staticmethod
    def _meeting_date(name: str) -> Optional[datetime.date]:
        """The meeting date printed in the document's title.

        `displayDate` is not used for this, for two reasons. It carries a "Z"
        suffix, but it is AWST wall time, not UTC: 595 of the 602 documents
        have a displayDate whose date part equals the date in the title,
        including every one stamped 18:00-20:00 "Z"—read as UTC, those would
        all fall on the next local day. And the other seven are listing dates
        a week or so before the meeting. The title is the council's own
        statement of when the meeting was held.

        A meeting held over two days ("12 & 15 August 2024") is dated by its
        first day.
        """
        match = _DATE.search(name)
        if not match:
            return None
        day, month, year = match.groups()
        return parse_date(f"{day} {month} {year}").date()

    def _document_label(self, name: str) -> str:
        parts = [p.strip() for p in _PART_SEPARATOR.split(name) if p.strip()]
        rest = [p for p in parts if not _DATE.search(p)]
        # The label is whichever remaining part is not the meeting type—
        # normally the last, but not always (see _PART_SEPARATOR).
        for part in reversed(rest):
            core = _SECOND_MEETING.sub("", part).lower()
            if _AGENDA_LABEL.match(core) or core in _MINUTES_LABELS:
                return part
        return rest[-1] if rest else ""

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        items = self._search(
            datetime.date(min(wanted), 1, 1) - _LISTING_SLACK,
            datetime.date(max(wanted), 12, 31) + _LISTING_SLACK,
        )
        # Raise rather than return []: an empty list counts as a working
        # council in the nightly run. The window reaches a month either side
        # of the wanted years, so it always takes in a December's meetings and
        # is never legitimately empty.
        if not items:
            raise RuntimeError(
                f"{self.council_name}: {_SEARCH_URL} returned no documents "
                f"for {min(wanted)}-{max(wanted)}"
            )

        # (meeting type, date, second meeting?) -> agenda/minutes
        meetings: dict[tuple, dict] = {}
        for item in items:
            name = re.sub(r"\s+", " ", item.get("name") or "").strip()
            url = item.get("urlPdf")
            if not url or not url.lower().endswith(".pdf"):
                # One "document" is a video of an electors' meeting.
                continue

            date = self._meeting_date(name)
            if date is None:
                self.logger.warning(f"No meeting date in {name!r}; skipped")
                continue
            if date.year not in wanted:
                continue

            label = self._document_label(name)
            second = bool(_SECOND_MEETING.match(label))
            label = _SECOND_MEETING.sub("", label).lower()

            # The category is the meeting type as the council files it, and
            # is consistent where the titles are not: the committee renamed
            # from "Audit and Risk" keeps one category across the rename.
            meeting_type = (item.get("category") or "").strip()
            key = (meeting_type, date, second)
            meeting = meetings.setdefault(
                key, {"agenda": None, "minutes": None, "minutes_rank": None}
            )

            if _AGENDA_LABEL.match(label):
                if meeting["agenda"] is None:
                    meeting["agenda"] = url
            elif label in _MINUTES_LABELS:
                rank = _MINUTES_LABELS[label]
                if meeting["minutes_rank"] is None or rank < meeting["minutes_rank"]:
                    meeting["minutes"] = url
                    meeting["minutes_rank"] = rank

        results = []
        for (meeting_type, date, second), docs in sorted(
            meetings.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2]),
            reverse=True,
        ):
            agenda_url, minutes_url = docs["agenda"], docs["minutes"]
            if not agenda_url and not minutes_url:
                # Only attachments or late items were published.
                continue
            name = meeting_type or "Council Meeting"
            if second:
                name = f"{name} (second meeting)"
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
