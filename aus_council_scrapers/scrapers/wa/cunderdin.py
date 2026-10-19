import datetime
import re
from typing import Optional

from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)

# "ordinary-council-meeting-28-october-2026", "...-27th-may-2026".
_SLUG_DATE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?-(january|february|march|april|may|june|july|"
    r"august|september|october|november|december)-(\d{4})/\d+/?$",
    re.IGNORECASE,
)

# "Confirmed Minutes OCM - 18th December 2024" is filed as
# "confirmed-minutes-ocm-18th-december-2024-incl-late-item-public-distribution.pdf":
# the minutes, with the late item's resolution in them. The base reads "late"
# in a filename as a late-items paper and would drop the meeting's minutes
# (October and December 2024).
_INCLUDES_LATE_ITEM = re.compile(r"-incl(?:uding)?-late-items?", re.IGNORECASE)
# "4.0 Minutes OCM - 17th September 2020": numbered like an agenda item, which
# the base takes for a single report, but the meeting's own minutes.
_SECTION_NUMBER = re.compile(r"^\s*\d+\.0\s+")


@register_scraper
class CunderdinScraper(ShireCouncilConnectScraper):
    """Shire of Cunderdin—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, so the audit
    committee, the LEMC, the Bush Fire Advisory Committee and the electors'
    meeting are left out; none is where planning decisions are made (scheme
    amendments go to the Council: 18 December 2024).

    The upcoming page lists every scheduled meeting a year ahead, with
    buttons that give the month only ("October 2026") and no dated title,
    so the base cannot tell which are close enough to have papers and would
    fetch all of them—seven extra requests a night, 2027 meetings included.
    The date is in the meeting's slug instead, which is made from its
    heading, so that is read to decide what to fetch. The meeting's date
    itself still comes from its page.

    Many 2021 meetings (8 of 13) and a few in 2020 (3 of 12) have minutes
    only: their pages hold no agenda.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 14 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("cunderdin", "WA", "https://www.cunderdin.wa.gov.au")

    @staticmethod
    def _link_date(link) -> Optional[datetime.date]:
        date = CouncilConnectScraper._link_date(link)
        if date:
            return date
        match = _SLUG_DATE.search(link.get("href", ""))
        if not match:
            return None
        try:
            return parse_date(" ".join(match.groups())).date()
        except (ValueError, OverflowError):
            return None

    def _fix_document(self, group, label, url):
        group, label, url = super()._fix_document(group, label, url)
        if re.search(r"minut", label, re.IGNORECASE):
            label = _SECTION_NUMBER.sub("", label)
            url = _INCLUDES_LATE_ITEM.sub("", url)
        return group, label, url
