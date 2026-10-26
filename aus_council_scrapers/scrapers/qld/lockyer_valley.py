from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class LockyerValleyScraper(InfoCouncilScraper):
    # Ordinary and special Council meetings only, monthly. Set for consistency
    # with the other new InfoCouncil councils: Lockyer's rows are already
    # clean, so the tidy flag changes nothing today but guards the first
    # supplementary agenda it lists.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "lockyer_valley",
            "QLD",
            "https://www.lockyervalley.qld.gov.au",
            "https://lockyervalley.infocouncil.biz/",
        )
