from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.scrapers.nsw.dotted_time import colon_times


@register_scraper
class SingletonScraper(InfoCouncilScraper):
    # The council's agendas-and-minutes page only frames this grid. Every body
    # is kept: the grid is one request a year whatever it lists, so narrowing
    # it saves nothing. The committee cell carries the venue ("Council
    # Chambers"), and most Council meetings have a "Council Meeting
    # Supplementary" row of their own, which is why the tidy flag is on.
    #
    # Asking for a year the grid does not hold (2027, 2028) returns the
    # current year's grid instead. Those rows are dated in the current year,
    # so the base class's check that each row's date is in the year asked
    # for already drops them.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "singleton",
            "NSW",
            "https://www.singleton.nsw.gov.au",
            "https://singleton.infocouncil.biz/",
        )

    def scraper(self) -> list[ScraperReturn]:
        # The grid writes most times with a dot ("5.30pm"), which the shared
        # time parsing misreads; see dotted_time.
        return colon_times(super().scraper())
