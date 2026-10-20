from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class EastFremantleScraper(CouncilConnectScraper):
    """Town of East Fremantle—documents on the year listing itself.

    The listing links each meeting's PDFs, so no meeting page is fetched for
    a past meeting, and committees cost nothing extra: every type is read.
    The listing's own PDF links are versioned and move whenever a meeting is
    edited, so the base emits each meeting page's version-free address.
    Past meetings carry no time or location: those are only on the meeting
    page, and reading it would cost a request per meeting.
    """

    # One production year, measured 19 Oct 2026 from a home IP in full
    # 135-council runs: 11.3 s at 10 workers, 13.4 s at 6. Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 12

    inline_documents = True

    def __init__(self):
        super().__init__("east_fremantle", "WA", "https://www.eastfremantle.wa.gov.au")
