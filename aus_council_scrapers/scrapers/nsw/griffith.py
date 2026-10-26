from aus_council_scrapers.base import InfoCouncilScraper, register_scraper


@register_scraper
class GriffithScraper(InfoCouncilScraper):
    # Self-hosted InfoCouncil. robots.txt is "Disallow: /" with exceptions for
    # "/$", "/Default.aspx", "/RedirectToDoc.aspx" and "/Open", so the year
    # pages must be asked for as "/Default.aspx?year=", never "/?year=".
    #
    # Papers go back to 2019; the site says older ones are by request. Late
    # agendas get rows of their own named "Council - Late Agenda", which the
    # tidy flag's name rule does not know, but every one is filed as _AT_SUP,
    # so the file rule strips its agenda and the row, left with no documents,
    # drops out.
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__(
            "griffith",
            "NSW",
            "https://www.griffith.nsw.gov.au",
            "https://businesspapers.griffith.nsw.gov.au/Default.aspx",
        )
