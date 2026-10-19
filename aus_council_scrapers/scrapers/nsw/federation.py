import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class FederationScraper(ResolveScraper):
    # Federation moved to Resolve for its 15 February 2022 meeting; the
    # tenant holds nothing earlier. Meetings from 2013 to 2021 are on the
    # OpenCities listing on the same council page
    # (https://www.federationcouncil.nsw.gov.au/Council/Council-Meetings/Minutes-Agendas),
    # which this scraper does not read yet.
    #
    # The 28 June 2022 Ordinary meeting is marked unpublished and the
    # council's portal does not show it, so it is left out even though
    # DocPreview serves its agenda and minutes.
    tenant = "federation"

    # Council meetings only ("Council Meeting", and "Council Meeting
    # 2024-2028" for this term). The Public Forum before most Council
    # meetings decides nothing.
    meeting_types = re.compile(r"^Council Meeting$")

    def __init__(self):
        super().__init__("federation", "NSW")
