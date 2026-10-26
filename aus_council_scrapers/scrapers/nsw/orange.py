from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class OrangeScraper(InfoCouncilScraper):
    # Orange lists Council alongside seven policy committees, Planning &
    # Development among them, all on the one year page, so keeping them all
    # costs nothing extra. Supplementary agendas ("Council Supplementary",
    # filed as _AT_SUP or _AT_SUP_EMBEDDED) get rows of their own, so the tidy
    # flag is on.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "orange",
            "NSW",
            "https://www.orange.nsw.gov.au",
            "https://orange.infocouncil.biz/",
        )
