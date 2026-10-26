from aus_council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class BaysideNSWScraper(InfoCouncilScraper):
    # infoweb.bayside.nsw.gov.au puts GitHub's runners behind a Cloudflare
    # challenge that nothing we tried passes (measured 19 Oct 2026: requests
    # with either User-Agent, Selenium with and without the headless marker,
    # Cloudflare WARP). From a home IP it serves 669 meetings. See AGENTS.md,
    # "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        council = "bayside_nsw"
        state = "NSW"
        base_url = "https://bayside.nsw.gov.au"
        # No `?committee=` filter: the base class appends `?year=<year>`, so a
        # URL that already carries a query string becomes `?committee=1?year=`,
        # which InfoCouncil reads as one committee value and answers with the
        # default (current year) listing for every year queried.
        infocouncil_url = "https://infoweb.bayside.nsw.gov.au/"
        super().__init__(council, state, base_url, infocouncil_url)
