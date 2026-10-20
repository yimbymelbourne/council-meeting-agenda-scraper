from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class RedlandScraper(InfoCouncilScraper):
    # Redland publishes only full Council and special meetings here, which is
    # where its planning decisions are made. Its supplementary rows carry an
    # upload stamp in the name ("Council - Supplementary uploaded 12/10/2026
    # 16:27"), which the tidy flag strips before folding them away.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "redland",
            "QLD",
            "https://www.redland.qld.gov.au",
            "https://redland.infocouncil.biz/",
        )
