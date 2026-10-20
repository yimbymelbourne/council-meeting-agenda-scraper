from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.moderngov import ModernGovScraper


@register_scraper
class CityOfSydneyScraper(ModernGovScraper):
    # Every meeting costs one page fetch (see ModernGovScraper), so the
    # committees are an allowlist rather than the 28 the site lists: Council,
    # and the two bodies that determine development applications—the
    # Central Sydney Planning Committee (applications over $50 million) and
    # the Local Planning Panel (contentious or sensitive applications staff
    # cannot decide under delegation). Between them that is about 37 meetings
    # a year.
    #
    # Left out on purpose: the Transport, Heritage and Planning Committee
    # (CId 137, about 10 meetings a year). It decides no DAs—it considers
    # planning proposals and heritage listings and recommends to Council,
    # whose agenda then carries its report. Add 137 here if the committee's
    # own papers are wanted.
    committees = {
        133: "Council",
        139: "Central Sydney Planning Committee",
        186: "Local Planning Panel",
    }

    # One production year, measured 19 Oct 2026 from a home IP: 107-115 s (30
    # requests: 3 listings and 27 meeting pages). Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 115

    def __init__(self):
        super().__init__("sydney", "NSW", "https://meetings.cityofsydney.nsw.gov.au")
