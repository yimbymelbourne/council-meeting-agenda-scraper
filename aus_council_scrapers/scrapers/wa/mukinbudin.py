from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)


@register_scraper
class MukinbudinScraper(SmallShireCouncilConnectScraper):
    """Shire of Mukinbudin—documents on each meeting's own page.

    The meetings module starts in 2021: /past/2020 is a 404. Headings number
    the meetings of the year ("8. September 2026 Ordinary Meeting of
    Council"), and the number is not part of the name. The audit committee is
    filed under "Special Council Meeting" and skipped by its heading.
    """

    first_year = 2021

    # Each checked by reading it (20 Oct 2026).
    wrong_documents = {
        "https://www.mukinbudin.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/6-july-2021-ordinary-meeting-of-council/142/documents"
        "/confirmed-minutes-of-special-meeting-24th-july-2021.pdf": (
            "the 24 June 2021 Special meeting's minutes, posted beside the July"
            " Ordinary meeting's own"
        ),
        "https://www.mukinbudin.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/2-annual-electors-meeting-22-march-2022/162/documents"
        "/20200128-annual-electors-meeting-agenda-2020.pdf": (
            "the agenda for the 18 February 2020 electors' meeting"
        ),
        "https://www.mukinbudin.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/annual-meeting-of-electors/138/documents"
        "/20200128-annual-electors-meeting-agenda-2020.pdf": (
            "the agenda for the 18 February 2020 electors' meeting"
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 28 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 28

    def __init__(self):
        super().__init__("mukinbudin", "WA", "https://www.mukinbudin.wa.gov.au")
