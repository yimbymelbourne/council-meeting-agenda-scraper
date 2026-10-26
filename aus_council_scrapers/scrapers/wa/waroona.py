import datetime
import re
from typing import Optional
from urllib.parse import unquote, urlparse

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import _FULL_DATE
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)

# "The Ordinary Council meeting commencing at 4.00 pm." under the date field
# on every 2020 meeting page.
_COMMENCING = re.compile(
    r"commencing\s+at\s+(\d{1,2})(?:[.:](\d{2}))?\s*([ap])\.?m", re.IGNORECASE
)


@register_scraper
class WaroonaScraper(WATidyCouncilConnectScraper):
    """Shire of Waroona—documents on each meeting's own page.

    Council meetings only: Ordinary and Special, about 12 a year. The other
    two types, the Audit, Risk & Improvement Committee and the electors'
    meeting, add one or two meetings a year and a request each.

    Headings and slugs name only the month ("December Ordinary Council
    Meeting", /december-ordinary-council-meeting/142); the date comes from
    the meeting page's date field.

    Through 2020 that field is an upload stamp rather than the meeting:
    "Monday, July 27, 2020 - 11:55 AM" above "The Ordinary Council meeting
    commencing at 4.00 pm." The time is read from that sentence instead.
    The day is usually right, but the June and July 2020 meetings are
    stamped the day before: their agendas are filed as "...-23-june-2020"
    and "...-28-july-2020", and both agendas and minutes say the 23rd and
    the 28th (read 20 Oct 2026). With the heading month-only, the base's
    test for a mis-entered date has no heading to go on, so a document
    filename stands in for it under the same rule: it names a date in the
    field's month, and no filename names the field's date. It is applied
    only to pages that carry the "commencing at" sentence, which are the
    stamped ones.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    name_by_type = True

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 13 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("waroona", "WA", "https://www.waroona.wa.gov.au")

    def _detail_links(self, soup, page_url):
        # The meeting page is parsed once, by the base; this is the one hook
        # that sees it, so the stated start time is noted here for
        # _meeting_from_detail.
        info = soup.find(class_="meeting-info")
        match = _COMMENCING.search(info.get_text(" ", strip=True)) if info else None
        self._commencing: Optional[str] = None
        if match:
            hour, minute, half = match.groups()
            self._commencing = f"{int(hour)}:{minute or '00'} {half.upper()}M"
        return super()._detail_links(soup, page_url)

    def _meeting_from_detail(self, url, labels, fallback_when=None):
        meeting = super()._meeting_from_detail(url, labels, fallback_when)
        if meeting is not None and getattr(self, "_commencing", None):
            meeting.time = self._commencing
        return meeting

    def _heading_date_if_documents_agree(
        self, heading: str, date: datetime.date, document_urls: list[str]
    ) -> datetime.date:
        date = super()._heading_date_if_documents_agree(heading, date, document_urls)
        # Only on the stamped pages, the ones with the "commencing at"
        # sentence. Elsewhere the field is the meeting's own date.
        if not getattr(self, "_commencing", None):
            return date
        filenames = [
            re.sub(r"[-_.]+", " ", unquote(urlparse(u).path.rsplit("/", 1)[-1]))
            for u in document_urls
        ]
        if any(self._names_date(f, date) for f in filenames):
            return date
        named = set()
        for filename in filenames:
            for day, month, year in _FULL_DATE.findall(filename):
                if not year:
                    continue
                try:
                    named.add(parse_date(f"{day} {month} {year}").date())
                except (ValueError, OverflowError):
                    continue
        same_month = {d for d in named if (d.year, d.month) == (date.year, date.month)}
        if len(same_month) == 1:
            filed = same_month.pop()
            self.logger.info(f"Date field says {date}, documents say {filed}")
            return filed
        return date
