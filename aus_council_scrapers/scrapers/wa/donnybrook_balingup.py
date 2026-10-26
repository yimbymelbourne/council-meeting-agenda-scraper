from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_tidy import (
    WATidyCouncilConnectScraper,
)


@register_scraper
class DonnybrookBalingupScraper(WATidyCouncilConnectScraper):
    """Shire of Donnybrook-Balingup—documents on each meeting's own page.

    Council meetings only. One type, "Committee Meeting", holds every
    committee—audit and risk, bush fire advisory, emergency management—and
    adds five to nine meetings a year, each a request. Ordinary and Special
    Council meetings were 18 in 2025 and 21 in 2024.

    The meetings module starts in 2019. Meeting slugs carry the date in
    parentheses (`ordinary-council-meeting-(17-december-2025)`), which the
    base's meeting-path pattern accepts.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }

    name_by_type = True

    # No meeting since 2020 started before 9:00 AM; the date field's "5:00
    # AM" and "7:00 AM" are typos (see the tidy module).
    earliest_hour = 8

    # One production year, measured 20 Oct 2026 from a home IP: 24 s for
    # 13 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 24

    def __init__(self):
        super().__init__(
            "donnybrook_balingup", "WA", "https://www.donnybrook-balingup.wa.gov.au"
        )
