from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.moderngov import ModernGovScraper


@register_scraper
class CityOfAdelaideScraper(ModernGovScraper):
    # Every meeting costs one page fetch (see ModernGovScraper), so the
    # committees are an allowlist rather than everything the site lists:
    # Council itself, and the Council Assessment Panel, which determines
    # development applications. Between them that is about 40 meetings a year.
    #
    # Left out on purpose: the City Planning, Development and Business Affairs
    # Committee (CId 192, about 11 meetings a year) only recommends—its
    # recommendations come back to Council and appear as an item on the
    # Council agenda—and Kadaltilla / Adelaide Park Lands Authority (155) is
    # advisory. Add 192 here if the committee's own papers are wanted.
    committees = {
        167: "Council",
        177: "Council Assessment Panel",
    }

    def __init__(self):
        super().__init__("adelaide", "SA", "https://meetings.cityofadelaide.com.au")
