from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)


@register_scraper
class LakeGraceScraper(ShireCouncilConnectScraper):
    """Shire of Lake Grace—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, so the electors'
    meeting and the Local Emergency Management Committee (2021–2022) are
    left out; neither is where planning decisions are made.

    The site names its types in the plural ("Ordinary Council Meetings"),
    and the base would emit that as each meeting's name. The names below
    are what a meeting is called, and with `meeting_types` set they win
    over the site's labels. Its headings are often the date alone ("26
    October 2022"), so the name comes from the type.
    """

    meeting_types = {
        "ordinary-council-meetings": "Ordinary Council Meeting",
        "special-council-meetings": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 27 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 27

    def __init__(self):
        super().__init__("lake_grace", "WA", "https://www.lakegrace.wa.gov.au")
