from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import CheckedDocsPublishedScraper


@register_scraper
class BusseltonScraper(CheckedDocsPublishedScraper):
    # busselton.wa.gov.au's minutes-and-agendas page links "Minutes and
    # Agendas (from 2025)" here; the list starts 22 January 2025. 2016-2024
    # are on the council's CMS, one page per year with direct PDF links,
    # and are not read yet: production asks only for the current year, and
    # that archive is a separate piece of work.
    #
    # The list held exactly 100 records on 20 Oct 2026, which looks like a
    # cap. It is probably not: the first record is 22 January 2025, which
    # matches the council's own "from 2025", and the same endpoint returns
    # 332 records for Wollondilly.
    publishing_slug = "cityofbusselton"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 43 s, against 11 s run alone.
    expected_seconds = 43

    def __init__(self):
        super().__init__("busselton", "WA")
