from aus_council_scrapers.base import register_scraper, InfoCouncilScraper


@register_scraper
class BaysideNSWScraper(InfoCouncilScraper):
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
