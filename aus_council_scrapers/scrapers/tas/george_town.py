from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.walkerdesigns import WalkerDesignsMeetingsScraper

# George Town Council. One page holds a table per year from 2021, upcoming
# meetings included. Agendas and minutes are the "Public Copy", with closed
# items removed. The AGM cells also hold the annual report tabled at it, and
# one agenda cell an item's report, which the base class leaves out; the
# 2023 AGM row carries the ordinary meeting's date (28 November) while its
# papers say 16 November, which the base class corrects. A production year
# is one request.
#
# Cloudflare fronts the site (server: cloudflare, CF-Ray); no challenge from a
# home IP with the identifying User-Agent. robots.txt disallows
# /cpresources/, /users/, planning applications and calendar pages, none of
# which this reads.


@register_scraper
class GeorgeTownScraper(WalkerDesignsMeetingsScraper):
    listing_url = "https://georgetown.tas.gov.au/council-meeting"
    earliest_year = 2021

    def __init__(self):
        super().__init__("george_town", "TAS", "https://georgetown.tas.gov.au")
