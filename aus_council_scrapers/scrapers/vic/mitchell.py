from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.vic.craft_agendas_minutes import (
    CraftAgendasMinutesTableScraper,
)

# Mitchell Shire Council. A SimpleGov Craft archive; the row parser is shared
# with Bass Coast (see `craft_agendas_minutes.py`) and the fetch-and-page loop
# with the SA Craft councils (`aus_council_scrapers/craft.py`). Eighty rows a
# page: 2020 to date is three pages, one year is one.
#
# Every body that meets in public is kept—Council, Special and Statutory
# Council meetings, the Community Questions and Hearings committee (which
# hears submissions, planning objections among them) and the joint meetings
# with Hume and Whittlesea—because the papers are on the listing itself and
# cost nothing more to read.
#
# The CloudFront in front of the site runs AWS WAF. A requests client
# identifying itself gets the 202 challenge with an empty body; with
# BROWSER_USER_AGENT it gets the page, from a home connection. From a GitHub
# runner that has not been measured, and five of the six SA Craft sites on
# the same setup challenge any requests client there, so this loads the
# listing in Chrome as they do. See the caveat in docs/councils.md.


@register_scraper
class MitchellScraper(CraftAgendasMinutesTableScraper):
    listing_url = (
        "https://www.mitchellshire.vic.gov.au/council/council-meetings/"
        "council-meetings/agendas-and-minutes"
    )

    def __init__(self):
        super().__init__("mitchell", "VIC", "https://www.mitchellshire.vic.gov.au")
