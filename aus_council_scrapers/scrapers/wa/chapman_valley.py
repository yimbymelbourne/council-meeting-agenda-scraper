from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_filtered import (
    FilteredListingCouncilConnectScraper,
)

_MEETING_79 = (
    "https://www.chapmanvalley.wa.gov.au/council-meetings/ordinary-council-meeting"
    "/ordinary-council-meeting/79"
)


@register_scraper
class ChapmanValleyScraper(FilteredListingCouncilConnectScraper):
    """Shire of Chapman Valley—documents on each meeting's own page.

    Council meetings, plus the Regional Development Assessment Panel: the
    state's development assessment panel sitting on a Chapman Valley
    application, which decides it in the council's place. Its one meeting
    in the module (No. 42, 14 May 2025) has an agenda and minutes. Its type
    page is a 404, though its meetings are on the all-types listing. The
    road, building and disability, and audit committees and the electors'
    meeting are left out, which keeps a production year near 17 requests.

    Meeting slugs are generic (`/ordinary-council-meeting/155`), so names
    and dates come from the page, as the base does anyway.
    """

    # One production year: 13 requests, 24 s from a home connection
    # (20 Oct 2026), most of it the 2 s per-host delay.
    expected_seconds = 24
    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "regional-development-assessment-panel": (
            "Regional Development Assessment Panel"
        ),
    }
    # Meeting 79, dated 17 August 2023, carries the agenda and minutes of
    # 18 August 2022—byte for byte the files on that meeting's own page
    # (/81), and both say "Thursday 18th August 2022" on the cover (read
    # 20 Oct 2026). The real 17 August 2023 meeting is /57.
    wrong_documents = {
        f"{_MEETING_79}/documents/ordinary-council-meeting-agenda-august-2022.pdf": (
            "18 August 2022 agenda, posted again on a 2023 meeting page"
        ),
        f"{_MEETING_79}/documents/ordinary-council-meeting-minutes-august-2022.pdf": (
            "18 August 2022 minutes, posted again on a 2023 meeting page"
        ),
    }

    def __init__(self):
        super().__init__("chapman_valley", "WA", "https://www.chapmanvalley.wa.gov.au")
