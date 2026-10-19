from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.walkerdesigns import WalkerDesignsMeetingsScraper

# Meander Valley Council. Every year from 2015 is a table on the one
# minutes-and-agendas page, upcoming meetings included (as rows with no
# documents until the agenda is out), so a production year is one request.
# Several rows need the base class's checks: agendas split into parts or
# page ranges, the 10 October 2023 minutes in the Agenda column, the
# November 2022 row dated a day late, and file names that are only upload
# hashes.
#
# Cloudflare fronts the site (server: cloudflare, CF-Ray); no challenge from a
# home IP with the identifying User-Agent. robots.txt disallows only
# /cpresources/.


@register_scraper
class MeanderValleyScraper(WalkerDesignsMeetingsScraper):
    listing_url = "https://www.meander.tas.gov.au/minutes-and-agendas"
    # The labels the council used before its 2026 table, mapped to the ones
    # it uses now.
    meeting_names = {
        "Council Meeting": "Ordinary Meeting",
        "Special Council Meeting": "Special Meeting",
        "Annual Meeting": "Annual General Meeting",
    }

    def __init__(self):
        super().__init__("meander_valley", "TAS", "https://www.meander.tas.gov.au")
