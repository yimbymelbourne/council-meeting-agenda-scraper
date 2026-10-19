"""Mareeba Shire Council (QLD).

The meetings page on msc.qld.gov.au is an empty shell: a script from
`websync.msc.qld.gov.au` reads `council_meetings/items.json`, a SharePoint
list export, and builds the table in the browser. That JSON is the whole
history in one request (2016 onward), so the scraper reads it directly and
never touches the Cloudflare-fronted main site. The websync host is plain
nginx and has no robots.txt (404, so no restriction).

Each item is a meeting with a `Meeting_x0020_Date` and its files. A file's
URL is built the way the widget builds it:
`/council_meetings/files/<item id>/<encodeURI(output_filename)>`.

Two quirks in how the council files things:

- An ordinary meeting's item often carries a same-day Special Council
  Meeting's papers too ("Special Council Meeting Agenda 19 July 2023" inside
  "Council Meeting 19 July 2023"), so files are sorted into meetings by
  their own names, not by the item they sit in.
- A special meeting's papers are sometimes split across several items
  ("Special Council Meeting Attachment 17 July 2024", "... - Agenda Listing -
  ..."), and those items hold neither an agenda nor minutes.

The committee page (`committee_meetings/items.json`) holds Audit, RADF and
advisory committee minutes, none of them decision-making or planning bodies,
so it is left out.
"""

from __future__ import annotations

import datetime
import json
import re
import urllib.parse
from typing import Optional

import pytz
from dateutil.parser import isoparse

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_SOURCE = "https://websync.msc.qld.gov.au/council_meetings"
_WEBPAGE = "https://msc.qld.gov.au/council/about-council/meetings-minutes-and-agendas/"
_TIMEZONE = pytz.timezone("Australia/Brisbane")

_MINUTES = re.compile(r"(?<![a-z])minutes(?![a-z])", re.IGNORECASE)
_AGENDA = re.compile(r"(?<![a-z])agenda(?![a-z])", re.IGNORECASE)
# Never the agenda: an attachment book, the order-of-business sheet, a late
# supplementary report.
_NOT_THE_PAPER = re.compile(r"attachment|listing|supplementary", re.IGNORECASE)

# Which meeting a file belongs to, read from its own name. Anything else is
# the item's own meeting.
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_POST_ELECTION = re.compile(r"\bpost[\s-]*election\b", re.IGNORECASE)

_DATE_WORDS = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+\d{4}\b|\b\d{1,2}/\d{1,2}/\d{4}\b",
    re.IGNORECASE,
)


def _meeting_type(text: str) -> str:
    """The meeting a title names: "Special Council Meeting Agenda 17 July
    2024" -> "Special Council Meeting"."""
    text = _DATE_WORDS.sub(" ", text)
    text = re.sub(
        r"(?<![a-z])(agenda|minutes|attachment)(?![a-z])", " ", text, flags=re.I
    )
    text = re.sub(r"[-–—]+", " ", text)
    return re.sub(r"\s+", " ", text).strip() or "Council Meeting"


def _comparable(name: str) -> str:
    return re.sub(r"[\s-]+", " ", name).strip().lower()


# The widget builds file URLs with JavaScript's encodeURI, which leaves these
# characters alone. Matching it keeps the URLs identical to the page's links.
_ENCODE_URI_SAFE = ";,/?:@&=+$-_.!~*'()#"


@register_scraper
class MareebaScraper(BaseScraper):
    def __init__(self):
        super().__init__("mareeba", "QLD", "https://msc.qld.gov.au")

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _local_date(value: str) -> Optional[datetime.date]:
        """The meeting's date in Queensland, whatever offset the export used."""
        try:
            moment = isoparse(value)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            return moment.date()
        return moment.astimezone(_TIMEZONE).date()

    @staticmethod
    def _file_meeting(file_name: str, item_meeting: str) -> str:
        if _POST_ELECTION.search(file_name):
            return "Post-Election Council Meeting"
        if _SPECIAL.search(file_name):
            return "Special Council Meeting"
        return item_meeting

    @staticmethod
    def _classify(file_name: str, meeting: str) -> Optional[str]:
        if _MINUTES.search(file_name):
            return "minutes"
        if _NOT_THE_PAPER.search(file_name):
            return None
        if _AGENDA.search(file_name):
            return "agenda"
        # A few agendas carry no "Agenda" in their name: "Special Council
        # Meeting 10 February 2025", "Post-Election Council Meeting - 15
        # April 2020". A file named after nothing but its meeting and date is
        # that meeting's paper; budgets and reports name something else.
        if _comparable(_meeting_type(file_name)) == _comparable(meeting):
            return "agenda"
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Raises on failure: this is the only request, so there is no partial
        # result worth returning instead.
        items = json.loads(self.fetcher.fetch_with_requests(f"{_SOURCE}/items.json"))
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"{_SOURCE}/items.json held no meetings")

        # (meeting, date) -> {"agenda": url, "minutes": url}
        meetings: dict[tuple[str, datetime.date], dict[str, str]] = {}
        for item in items:
            date = self._local_date(item.get("Meeting_x0020_Date"))
            if date is None:
                self.logger.warning(f"Item {item.get('id')} has no usable meeting date")
                continue
            if date.year not in wanted:
                continue
            item_meeting = _meeting_type(item.get("Title") or "")
            for attachment in item.get("attachments") or []:
                file_name = (
                    attachment.get("name") or attachment.get("output_filename") or ""
                )
                output = attachment.get("output_filename")
                if not output or (attachment.get("extension") or "").lower() != "pdf":
                    continue
                meeting = self._file_meeting(file_name, item_meeting)
                kind = self._classify(file_name, meeting)
                if kind is None:
                    continue
                url = f"{_SOURCE}/files/{item['id']}/{urllib.parse.quote(output, safe=_ENCODE_URI_SAFE)}"
                # First of each kind wins; items list their files in name
                # order, and no meeting here carries two of either.
                meetings.setdefault((meeting, date), {}).setdefault(kind, url)

        results = []
        for (meeting, date), papers in sorted(
            meetings.items(), key=lambda kv: (kv[0][1], kv[0][0])
        ):
            agenda_url = papers.get("agenda")
            minutes_url = papers.get("minutes")
            results.append(
                ScraperReturn(
                    name=meeting,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_WEBPAGE,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            message = (
                f"{self.council_name}: items.json held no meetings for {sorted(wanted)}"
            )
            # The council meets monthly and posts each agenda days ahead, so
            # a year three months old with nothing in it means the export
            # has changed shape, not that nobody met.
            if clock.today() - datetime.date(min(wanted), 1, 1) > datetime.timedelta(
                days=90
            ):
                raise RuntimeError(message)
            self.logger.warning(message)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
