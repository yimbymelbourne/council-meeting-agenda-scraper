from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class IpswichScraper(InfoCouncilScraper):
    # Ipswich lists about a hundred rows a year across Council, six standing
    # committees (Infrastructure, Planning and Assets is the planning one) and
    # councillor briefings. All are kept: the grid costs one request per year
    # however many bodies it holds. Supplementary rows are folded away by the
    # tidy flag.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "ipswich",
            "QLD",
            "https://www.ipswich.qld.gov.au",
            "https://ipswich.infocouncil.biz/",
        )
