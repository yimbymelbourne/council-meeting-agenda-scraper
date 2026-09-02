from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class NillumbikScraper(InfoCouncilScraper):
    def __init__(self):
        council = "nillumbik"
        state = "VIC"
        base_url = "https://www.nillumbik.vic.gov.au"
        # The council's own page links default.aspx?committee=1, which narrows
        # the grid to Council meetings. The unfiltered page carries those plus
        # the committees, and the base class appends its own ?year=, so the
        # filtered URL could not be used as-is anyway.
        infocouncil_url = "https://nillumbik.infocouncil.biz/Default.aspx"
        super().__init__(council, state, base_url, infocouncil_url)
