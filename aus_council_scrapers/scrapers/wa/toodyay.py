import datetime
import re
from typing import Optional

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)

# Toodyay's template writes the date day first and with no time: "Thursday,
# 18 December, 2025", on the meeting page and the listing alike. The base
# reads only the US order ("December 18, 2025 - 06:00 PM") and would find no
# date on any meeting.
_DAY_FIRST_DATE = re.compile(
    r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December),?\s+\d{4}\b",
    re.IGNORECASE,
)


@register_scraper
class ToodyayScraper(WATidyCouncilConnectScraper):
    """Shire of Toodyay—documents on each meeting's own page.

    Council meetings only. A year runs to 35–45 meetings, each a request:
    the audit, bush fire, emergency management, infrastructure and works
    committees, the Avon Midland Peri-Urban Partnership and others. Ordinary
    and Special Council meetings alone were 21 in 2024 and 17 by October
    2026.

    The upcoming page lists the whole schedule a year ahead (41 meetings in
    October 2026), each with a dated button, so the base skips everything
    but the Council meetings within four weeks without fetching them.

    Meeting slugs and headings are generic ("Ordinary Council Meeting",
    /ordinary-council-meeting/642), so the date is only in the date field.
    The listing and meeting pages give no meeting time.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-council-meetings": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 43 s for
    # 21 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 43

    def __init__(self):
        super().__init__("toodyay", "WA", "https://www.toodyay.wa.gov.au")

    @staticmethod
    def _parse_when(
        text: str,
    ) -> tuple[Optional[datetime.date], Optional[str]]:
        date, time = CouncilConnectScraper._parse_when(text)
        if date is not None:
            return date, time
        match = _DAY_FIRST_DATE.search(text or "")
        if not match:
            return None, None
        return parse_date(match.group().replace(",", "")).date(), None
