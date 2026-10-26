from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper


@register_scraper
class WyndhamEastKimberleyScraper(TidyCouncilConnectScraper):
    """Shire of Wyndham-East Kimberley—documents on each meeting's own page.

    Council meetings only. The audit committee, the East Kimberley Regional
    Airport Committee and the Wyndham "Meet and Greet" sessions each cost a
    request a meeting and carry nothing on planning.

    Meeting slugs name the venue, not the date
    (`/ordinary-council-meeting-kununurra-council-chambers/193`), and every
    meeting of a type shares one, so dates and names come from the page—
    which the base does anyway. Pre-2017 papers are in a document-centre
    archive outside the meetings module and are not read.

    Not to be confused with City of Wyndham (VIC), the `wyndham` scraper.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    # The /past index starts at 2017.
    first_year = 2017

    wrong_documents = {
        "https://www.swek.wa.gov.au/council-meetings/ordinary-council-meeting/"
        "ordinary-council-meeting-kununurra/154/documents/"
        "2407_confirmed_minutes_ordinary_council_meeting_-_23_july_2024.pdf": (
            "The 23 July 2024 meeting's minutes (confirmed on 27 August, which "
            "is why they are on that page), read 20 Oct 2026. The 27 August "
            "2024 meeting's own minutes are not on its page."
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s (14
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("wyndham_east_kimberley", "WA", "https://www.swek.wa.gov.au")
