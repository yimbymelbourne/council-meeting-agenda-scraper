from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect_tidy import TidyCouncilConnectScraper


@register_scraper
class AshburtonScraper(TidyCouncilConnectScraper):
    """Shire of Ashburton—documents on each meeting's own page.

    Council meetings only. The shire runs half a dozen committees (audit,
    economic and tourism development, community grants, waste, CEO review),
    each meeting a request; Ordinary and Special meetings of Council alone
    keep a production year near 20.

    The site is behind Cloudflare (`server: cloudflare`), which served plain
    requests without a challenge from a home IP on 20 Oct 2026. Nothing has
    been measured from a GitHub runner.
    """

    meeting_types = {
        "ordinary-meeting-of-council": "Ordinary Meeting of Council",
        "special-meeting-of-council": "Special Meeting of Council",
    }

    # Headings are hand-typed ("Special Meeting", "Special Council Meeting -
    # By Electronic Means"); the type names are clean.
    name_by_type = True

    wrong_documents = {
        "https://www.ashburton.wa.gov.au/council-meetings/ordinary-meeting-of-council/"
        "ordinary-council-meeting/294/documents/"
        "confirmed-minutes-special-council-meeting-2022-03-03-public.pdf": (
            "Confirmed minutes of the 3 March 2022 Special Council Meeting "
            "(front page read 20 Oct 2026), listed first among the 8 March "
            "2022 Ordinary meeting's minutes; that meeting's own confirmed "
            "minutes are on the same page."
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 31 s (16
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 31

    def __init__(self):
        super().__init__("ashburton", "WA", "https://www.ashburton.wa.gov.au")
