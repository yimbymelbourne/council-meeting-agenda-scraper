from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class CoorowScraper(InfoCouncilScraper):
    # Coorow moved its papers to InfoCouncil in December 2022: the 2022 grid
    # holds one meeting (14 Dec, agenda only), and asking for any earlier
    # year returns the current year's grid, which the base class discards
    # because the dates do not match. The shire's WordPress meetings page
    # holds only audio recordings (per the scout; not re-checked).
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "coorow",
            "WA",
            "https://coorow.wa.gov.au",
            "https://coorow.infocouncil.biz/",
        )
