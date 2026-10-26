import datetime

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.datascape import DatascapeMeetingsScraper

# Shire of Halls Creek. One item per document, not per meeting: "Ordinary
# Council Meeting Agenda September 2026" and "Ordinary Council Meeting Minutes
# 24 September 2026" are separate items in separate categories, so the base
# class pairs them by body and date. The listing's Date: field is when the
# paper went up (the minutes of 27 November 2025 are dated 18 December), so it
# is not used as the meeting's date, with one exception. An agenda named by
# month only ("OCM Agenda April 2026 14.4.26 at 0907hrs.pdf") has nothing else
# to date it until its minutes go up, so upcoming agendas would always be
# missed. Its listing Date: is the meeting's day when it falls on a Thursday,
# the ordinary meeting day, at midnight in the named month: every such entry
# whose meeting day is known checks out, and the upload stamps fall on other
# days or carry a time (`listed_meeting_weekday`; counts in datascape.py).
# All categories are listed on one page
# a year; only the ordinary and special Council agendas and minutes are read
# (late agenda items, audio and committees are not).
#
# Cloudflare fronts the site (server: cloudflare, cf-ray); no challenge from
# a home IP with the identifying User-Agent, not yet seen from a GitHub
# runner. robots.txt: Allow / with Crawl-delay: 7. Because of Cloudflare,
# Datascape's server sees Cloudflare's addresses rather than ours, so this
# council does not take turns with the other three (`backend = None`): it
# never had an empty page in 163 requests run beside them.


@register_scraper
class HallsCreekScraper(DatascapeMeetingsScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    listing_url = "https://www.hallscreek.wa.gov.au/council/meetings"
    keep_categories = r"^(?:Ordinary|Special) Council Meeting (?:Agendas|Minutes)?$"
    items_are_documents = True
    trust_listed_dates = False
    listed_meeting_weekday = 3  # Thursday
    # Read from the agenda's cover (20 Oct 2026). It is listed on Sunday 13
    # June 2021, and no minutes for it are on the site.
    known_meeting_dates = {
        ("ordinary", 2021, 6): datetime.date(2021, 6, 17),
    }
    backend = None
    expected_seconds = 140.0

    def __init__(self):
        super().__init__("halls_creek", "WA", "https://www.hallscreek.wa.gov.au")
