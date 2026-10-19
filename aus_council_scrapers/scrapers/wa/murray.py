from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper


@register_scraper
class MurrayWAScraper(CouncilConnectScraper):
    """Shire of Murray—documents on each meeting's own page.

    Council meetings only. A year is ~20 meetings, and the other half are the
    emergency management, bush fire advisory, audit and CEO review
    committees and the electors' meeting; leaving them out keeps one
    production year at 14 requests (2026) instead of ~25.

    The meetings module starts in October 2021: its /past index lists 2021
    onward, and /past/2020 and /past/2019 are 404s. Nothing older is in the
    module.

    Meeting slugs are generic (`/ordinary-council-meeting/176`), so names and
    dates come from the page, never the URL—which the base does anyway.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    first_year = 2021

    def __init__(self):
        super().__init__("murray", "WA", "https://www.murray.wa.gov.au")
