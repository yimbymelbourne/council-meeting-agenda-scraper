from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class LismoreScraper(InfoCouncilScraper):
    # Supplementary agendas get rows of their own ("Council Supplementary"),
    # some carrying only a supplementary attachments file, so the tidy flag is
    # on and those rows fold onto their meeting or drop out.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "lismore",
            "NSW",
            "https://www.lismore.nsw.gov.au",
            "https://lismore.infocouncil.biz/",
        )
