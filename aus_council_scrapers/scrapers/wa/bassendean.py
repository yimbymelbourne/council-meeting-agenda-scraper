from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class BassendeanScraper(CouncilConnectScraper):
    """Town of Bassendean—documents on each meeting's own page.

    Council meetings only. A year runs to ~40 meetings, each a request, and
    more than half are Briefing Sessions (the councillors' run-through of the
    coming agenda) and committees—audit, emergency management, arts, the
    padel courts project. Ordinary and Special Council meetings alone took
    16 requests for 2026.

    `/council-meetings/` is a landing page here, not the upcoming list, so
    upcoming meetings are read from each type's own page.

    Meeting slugs are generic (`/ordinary-council-meeting/673`), so names and
    dates come from the page, never the URL.

    The town sometimes posts an agenda or unconfirmed minutes only as a Word
    file (the 25 August and 6 October 2026 meetings, among others). Only PDFs
    are read, so those meetings carry what PDFs they have, or are left out
    when they have none.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    upcoming_path = (
        "/council-meetings/ordinary-council-meeting",
        "/council-meetings/special-council-meeting",
    )

    # Not a typo in the filename: this PDF is the 20 May 2025 Special
    # meeting's minutes (business "Annual Budget 2025/26 - Proposed
    # Differential Rates", opened 6:02 pm), re-signed 26 May 2026 and posted
    # on the 19 May 2026 meeting, whose agenda is about the 2026/27 budget
    # and a 5:45 pm start. The 2025 meeting (/660) carries its own copy. Drop
    # this entry once the town posts the right minutes, which will have a
    # different filename.
    wrong_documents = {
        "https://www.bassendean.wa.gov.au/council-meetings/special-council-meeting"
        "/special-council-meeting/699/documents"
        "/special_council_meeting_20_may_2025_confirmed_minutes.pdf": (
            "the 20 May 2025 Special meeting's minutes, posted on 19 May 2026's"
        ),
    }

    # One production year, measured 19 Oct 2026 from a home IP: 31 s (16
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 31

    def __init__(self):
        super().__init__("bassendean", "WA", "https://www.bassendean.wa.gov.au")
