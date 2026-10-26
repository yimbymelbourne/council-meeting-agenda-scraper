from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.scrapers.nsw.dotted_time import colon_times


@register_scraper
class NambuccaValleyScraper(InfoCouncilScraper):
    # The council's Business Papers page carries only meeting audio; the
    # papers are all on this grid. Every body is kept (Access, Traffic and
    # Vehicular Access to Beaches committees in the early years): the grid is
    # one request a year whatever it lists.
    #
    # The tidy flag folds the "Ordinary Council Supplementary" rows onto
    # their meetings, and also mends a name InfoCouncil doubles: an
    # extraordinary meeting of the "Extraordinary Council Meeting" committee
    # is listed as "Extraordinary Extraordinary Council Meeting".
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "nambucca_valley",
            "NSW",
            "https://www.nambucca.nsw.gov.au",
            "https://nambucca.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        # The grid writes most times with a dot ("5.30pm"), which the shared
        # time parsing misreads; see dotted_time.
        return colon_times(super().scraper())
