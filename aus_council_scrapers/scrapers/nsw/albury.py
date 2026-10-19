from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import CheckedDocsPublishedScraper


@register_scraper
class AlburyScraper(CheckedDocsPublishedScraper):
    # alburycity.nsw.gov.au's meetings page links here. DocsPublished starts
    # in February 2024; older papers on the council's Drupal site are not
    # read. Pre-meeting Briefing Sessions and Public/Community Forums
    # publish an agenda and no minutes, and are kept as their own meetings.
    #
    # Two committee records (7 and 13 April 2026) carry minutes in the
    # agenda slot—the 13 April one is the 11 May meeting's—which the base
    # checks drop.
    publishing_slug = "alburycity"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 56 s, against 11 s run alone.
    expected_seconds = 56

    def __init__(self):
        super().__init__("albury", "NSW")
