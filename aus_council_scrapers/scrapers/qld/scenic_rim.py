from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class ScenicRimScraper(InfoCouncilScraper):
    # The case the tidy flag was written for: the committee cell carries the
    # Beaudesert venue, and over half of the 2026 grid rows are supplementary
    # agendas listed as rows of their own.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "scenic_rim",
            "QLD",
            "https://www.scenicrim.qld.gov.au",
            "https://scenicrim.infocouncil.biz/",
        )
