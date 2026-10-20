from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import CheckedDocsPublishedScraper


@register_scraper
class WestDalyScraper(CheckedDocsPublishedScraper):
    # westdaly.nt.gov.au is a Duda site with no meeting links; the tenant was
    # found by probing api.docassembler.com.au and confirmed by its
    # organisation name. History starts January 2023. The three Local
    # Authorities (Wadeye, Nganmarriyanga [Palumpa], Peppimenarti) are
    # kept: in a regional council they are where community matters are
    # heard.
    #
    # Four records hold minutes in the agenda slot and two a supplementary
    # or finance report; the base checks move or drop them. 2023's records
    # carry a date and no time.
    publishing_slug = "westdaly"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 46 s, against 6 s run alone.
    expected_seconds = 46

    def __init__(self):
        super().__init__("west_daly", "NT")
