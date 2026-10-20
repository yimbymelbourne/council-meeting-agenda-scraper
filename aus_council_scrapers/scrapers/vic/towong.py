from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.datascape import DatascapeMeetingsScraper

# Towong Shire Council. One item per meeting, titled "Ordinary Council
# Meeting - 26 November 2025 - Tallangatta". The listing's own Date: field is
# a placeholder on several items (1 April, 1 March), so the date is read from
# the title and the papers, never from it. The Corryong Cemeteries Trust is
# listed alongside and left out by category. The listing starts in 2021.
#
# Served direct (x-powered-by: ASP.NET), no CDN or WAF headers seen from a
# home IP. robots.txt: Allow / with Crawl-delay: 7.


@register_scraper
class TowongScraper(DatascapeMeetingsScraper):
    listing_url = (
        "https://www.towong.vic.gov.au/1-council/meetings-and-public-question-time"
        "/council-meetings"
    )
    keep_categories = r"^(?:Ordinary|Special)$"
    earliest_year = 2021
    # Its own share is about 85-90 s (13 requests at the 7 s crawl delay)
    # for a production year, but it takes turns with the other councils on
    # Datascape's shared server, and the three together took 270-274 s
    # (20 Oct 2026). Set to the group's time so all three start first.
    expected_seconds = 275.0

    def __init__(self):
        super().__init__("towong", "VIC", "https://www.towong.vic.gov.au")
