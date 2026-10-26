"""The Barossa Council.

The Craft "meetings module" layout (see `aus_council_scrapers/craft.py`),
on one unpaged page. The council keeps a rolling window—"documents for
meetings over at least the last 3 years will remain online"—so the earliest
year in the fixture moves forward as it prunes, and that is the council's
choice rather than a regression.

Addenda and attachments sit in each meeting's `documents/` folder, beside the
agenda rather than as it, and a cancelled workshop gets a `NO-AGENDA.pdf`
placeholder; `classify_document` drops both.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.craft import CraftMeetingsModuleScraper


@register_scraper
class BarossaScraper(CraftMeetingsModuleScraper):
    listing_url = "https://www.barossa.sa.gov.au/council/agendas-and-minutes-2"

    # From a GitHub-hosted runner, plain requests get the AWS WAF challenge
    # whatever the User-Agent. Headless Chrome has not been measured from
    # there. From a home IP on 19 October 2026 a 2026 run returned 47
    # meetings both ways, stripped and unstripped, so stripping costs
    # nothing on this one-page, no-postback listing. (Adelaide Hills, by
    # contrast, times out unstripped even from home.) It is kept as a guard
    # against the runner-side 403 that Adelaide Hills' CloudFront gives the
    # HeadlessChrome token; a runner run both ways would settle it.
    strip_headless_user_agent = True

    def __init__(self):
        super().__init__("barossa", "SA", "https://www.barossa.sa.gov.au")
