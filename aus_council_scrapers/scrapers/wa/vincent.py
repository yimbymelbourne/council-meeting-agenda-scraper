from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)


@register_scraper
class VincentScraper(InfoCouncilScraper):
    # InfoCouncil holds Vincent's meetings from 2017; anything older is on the
    # council's own site and out of range anyway. The venue sits in the
    # committee cell, and late items get rows of their own, so the tidy flag
    # is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "vincent",
            "WA",
            "https://www.vincent.wa.gov.au",
            "https://vincent.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        # The 2025 grid carries a "Dummy Page" row dated 1 January with an
        # agenda PDF attached: an InfoCouncil placeholder, not a meeting.
        return [m for m in super().scraper() if m.name != "Dummy Page"]
