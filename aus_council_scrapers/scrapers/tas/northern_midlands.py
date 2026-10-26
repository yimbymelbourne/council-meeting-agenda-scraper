from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.walkerdesigns import WalkerDesignsMeetingsScraper

# Northern Midlands Council. One page holds a table per year from 2015, with
# an Attachments column between the agenda and the minutes; the attachments
# are not stored. Above the tables is the year's schedule of ordinary meeting
# dates, a header-less table the base class skips. A meeting appears only
# once its agenda is up, so there are no empty upcoming rows. A production
# year is one request (the page is about 800 KB).
#
# Apache, no CDN in front. robots.txt disallows only /cpresources/.


@register_scraper
class NorthernMidlandsScraper(WalkerDesignsMeetingsScraper):
    listing_url = (
        "https://northernmidlands.tas.gov.au/council/your-council/council-meetings"
    )
    # Special meetings are "Special Meeting of Council" until July 2025 and
    # "Special Council Meeting" since; the older label is mapped to the
    # newer one.
    meeting_names = {"Special Meeting of Council": "Special Council Meeting"}

    def __init__(self):
        super().__init__(
            "northern_midlands", "TAS", "https://northernmidlands.tas.gov.au"
        )
