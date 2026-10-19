"""City of Salisbury.

The Craft "meetings module" layout (see `aus_council_scrapers/craft.py`),
paged by path at about 30 meetings a page across roughly thirty committees
and working groups. The custom date filter works with ISO dates. It only
looked broken because the `DD/MM/YYYY` the date picker shows answers HTTP
500. So a production year is four or five page loads rather than a walk down
from page 1 of the whole history.

Every page of a query repeats the same upcoming-meetings panel, which the
base class de-duplicates. A meeting that starts "at the conclusion of" the
one before it shows `*` where the time would be, and so has no time.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import CraftMeetingsModuleScraper


@register_scraper
class SalisburyScraper(CraftMeetingsModuleScraper):
    # One production year, measured 19 Oct 2026 from a home IP in full
    # 135-council runs: 17.3 s at 10 workers, 15.5 s at 6. Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 17

    listing_url = "https://www.salisbury.sa.gov.au/council/meeting-agendas-and-minutes"

    # From a GitHub-hosted runner, plain requests get the AWS WAF challenge
    # whatever the User-Agent; headless Chrome passes unmodified.

    def __init__(self):
        super().__init__("salisbury", "SA", "https://www.salisbury.sa.gov.au")
