from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class BallinaScraper(InfoCouncilScraper):
    # InfoCouncil holds Ballina's papers from 2022 only; asking for 2020 or
    # 2021 returns the current year's grid, which the base class drops by
    # date. Supplementary agendas get rows of their own ("Council
    # Supplementary"), so the tidy flag is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "ballina",
            "NSW",
            "https://www.ballina.nsw.gov.au",
            "https://ballina.infocouncil.biz/",
        )
