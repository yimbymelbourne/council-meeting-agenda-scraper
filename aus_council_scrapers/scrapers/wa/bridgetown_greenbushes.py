from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)


@register_scraper
class BridgetownGreenbushesScraper(WATidyCouncilConnectScraper):
    """Shire of Bridgetown-Greenbushes—documents on each meeting's own page.

    Council meetings only. The others are the electors' meeting and, from
    2026, the Audit Risk and Improvement Committee (filed as "Standing
    Committee Meeting"). That saves little, but the Shire holds a lot of
    Special meetings—14 in 2025, as well as 12 Ordinary—so 2025 alone cost
    about 29 requests; 2026 to October, 13.

    The Ordinary type's slug is plain `council-meeting`, which the base
    would show as "Council Meeting"; it is named for what it is.
    """

    meeting_types = {
        "council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    name_by_type = True

    # Every meeting starts at 1 PM or later; the one "5:30 AM" (27 May
    # 2021) is a typo for 5.30pm. See the tidy module.
    earliest_hour = 8

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 13 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__(
            "bridgetown_greenbushes", "WA", "https://www.bridgetown.wa.gov.au"
        )

    def _pick_documents(self, links, meeting_name=None, date=None):
        # "Council Agenda & Attachments - July 2020" is the agenda packet.
        # The base recognises a packet written "and attachments" and reads
        # the ampersand form as an attachment, which left every 2020 Council
        # meeting without its agenda. The briefing and Q&A papers filed
        # above the agenda ("Draft OCM Agenda for Q&A 16 April 2025") are
        # dropped by the tidy base.
        return super()._pick_documents(
            [(group, label.replace("&", " and "), url) for group, label, url in links]
        )
