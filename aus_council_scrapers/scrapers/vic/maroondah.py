from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class MaroondahScraper(InfoCouncilScraper):
    # The council's own Agendas-and-minutes page (OpenCities) only links out
    # to InfoCouncil, which holds every Ordinary and Statutory Council meeting
    # from 2014 with agenda and minutes on one grid row. A year is one
    # request. Maroondah's rows are already clean—no venue in the committee
    # cell, no supplementary rows—so the tidy flag changes nothing today but
    # guards the first supplementary agenda it lists.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "maroondah",
            "VIC",
            "https://www.maroondah.vic.gov.au",
            "https://maroondah.infocouncil.biz/",
        )
