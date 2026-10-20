from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class SunshineCoastScraper(InfoCouncilScraper):
    # InfoCouncil starts at April 2020; January to March 2020 sit only on the
    # council's archive page and are not fetched. The committee cell carries
    # the venue and most meetings have empty "Supplementary" rows, hence the
    # tidy flag.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "sunshine_coast",
            "QLD",
            "https://www.sunshinecoast.qld.gov.au",
            "https://sunshinecoast.infocouncil.biz/",
        )
