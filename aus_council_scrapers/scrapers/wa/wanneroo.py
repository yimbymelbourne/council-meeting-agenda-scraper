from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class WannerooScraper(InfoCouncilScraper):
    # Every body is kept, briefings and advisory committees included: the grid
    # is one request per year whatever it lists, so narrowing it saves nothing.
    # "Agenda Briefing - Supplementary" rows are why the tidy flag is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "wanneroo",
            "WA",
            "https://www.wanneroo.wa.gov.au",
            "https://wanneroo.infocouncil.biz/",
        )
