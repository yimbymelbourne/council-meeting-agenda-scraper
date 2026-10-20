from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.wpfd import WPFDListing, WPFileDownloadScraper

# Central Coast Council (Tasmania; not Central Coast NSW). The agendas-minutes
# page carries this year and last, one WP File Download category per meeting;
# the archive page carries 2019–2025. Some 2024 category slugs have no year
# ("15-april"), so the date comes from the files, which always name it.
#
# One category can hold two meetings: the AGM and the ordinary meeting held
# the same December evening share a category, and are told apart by the "AGM"
# in the AGM's file titles.
#
# The Planning Sub-Committee (planning applications, last met February 2024)
# has a page of its own whose file titles do not name the committee, so the
# listing names it.
#
# A production year is two requests. Cloudflare fronts the site; no challenge
# from a home IP. robots.txt disallows only /wp-admin/.


@register_scraper
class CentralCoastTasScraper(WPFileDownloadScraper):
    listings = (
        WPFDListing(
            "https://www.centralcoast.tas.gov.au/council/meetings/agendas-minutes/"
        ),
        WPFDListing(
            "https://www.centralcoast.tas.gov.au/council/meetings/agendas-minutes/archive/",
            archive=True,
        ),
        WPFDListing(
            "https://www.centralcoast.tas.gov.au/council/meetings/planning-sub-committee/",
            default_name="Planning Sub-Committee",
        ),
    )

    def __init__(self):
        super().__init__(
            "central_coast_tas", "TAS", "https://www.centralcoast.tas.gov.au"
        )
