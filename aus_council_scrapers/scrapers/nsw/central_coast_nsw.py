from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.docspublished_checked import CheckedDocsPublishedScraper


@register_scraper
class CentralCoastNSWScraper(CheckedDocsPublishedScraper):
    # "Agendas, Business Papers and Minutes" on centralcoast.nsw.gov.au links
    # here. DocsPublished holds every meeting from 27 January 2021; the
    # 2016-2020 papers (and Gosford's and Wyong's before the merger) are on
    # the council's own Drupal site, which answers our identifying
    # User-Agent with a CloudFront 403 and is not read.
    #
    # This is the tenant the checks in CheckedDocsPublishedScraper were
    # written for: 24 records from 2021 to 2025 carry the "Supplementary
    # Attachments Paper" (`... Agenda Attachment SUP.pdf`) in the agenda slot,
    # 22 of them with the business paper among the supporting documents, and
    # three hold a paper filed on the wrong meeting. "Agenda Attachment" without SUP is
    # InfoCouncil's agenda-with-attachments, the full business paper.
    #
    # All committees are kept, not just Council and the Local Planning Panel:
    # the whole history is one list, so they cost no extra request.
    publishing_slug = "centralcoastcouncil"

    # Measured 20 Oct 2026 in one --years 2026 run with all 15 DocsPublished
    # councils. They share DocAssembler's API, portal and blob hosts, so
    # they queue on one per-host spacing: 54 s, against 17 s run alone.
    expected_seconds = 54

    def __init__(self):
        super().__init__("central_coast_nsw", "NSW")
