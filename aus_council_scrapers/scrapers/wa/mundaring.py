import datetime
import re
from urllib.parse import urljoin

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper
from aus_council_scrapers.resolve import ResolveScraper

SITE = "https://www.mundaring.wa.gov.au"


@register_scraper
class MundaringScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 7.8 s alone,
    # 17.7 s in a full 135-council run at 10 workers, queued with the other
    # tenants on api.resolve.red. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 18

    # The Shire's council-meetings page says Resolve holds every agenda from
    # 1 July 2025 and frames the tenant's /web/ portal; the tenant's first
    # event is the 8 July 2025 Ordinary Council Meeting. Meetings from 2016
    # to June 2025 are in the CouncilConnect library the site still serves
    # at /council-meetings/past/<year>, read by `other_meetings`. Production
    # asks for a year that is all Resolve, so the library costs it nothing.
    #
    # The library also lists "Ordinary Council Meeting - 8 July 2025", dated
    # Sunday 8 June 2025 and with no documents. It is skipped as a meeting
    # with no papers, and would be dropped as on or after the move if it
    # had any; the tenant has the meeting.
    tenant = "mundaring"
    resolve_from = datetime.date(2025, 7, 1)

    # Ordinary and Special Council, and the swearing-in ceremony, which the
    # library files as a special Council meeting (25 October 2023). Left out
    # are the audit, governance, grants, emergency management, bush fire, CEO
    # review and Australia Day committees and the electors' meeting; each
    # kept meeting costs a request to learn which documents it has.
    meeting_types = re.compile(
        r"^(Ordinary Council|Special Council|Swearing in Ceremony)$"
    )
    # Named as the library names the same meetings, so a meeting type reads
    # the same either side of the move.
    meeting_type_names = {
        "Ordinary Council": "Ordinary Council Meeting",
        "Special Council": "Special Council Meeting",
    }

    def __init__(self):
        super().__init__("mundaring", "WA")

    def other_meetings(self, wanted: set[int]) -> list[ScraperReturn]:
        years = self.before_resolve(wanted)
        if not years:
            return []
        library = _Library(self)
        library.years_filter = years
        return [r for r in library.scraper() if r.date < self.resolve_from.isoformat()]


class _Library(CouncilConnectScraper):
    """Mundaring's CouncilConnect library, read through the owner's fetcher.

    Council meetings only. The per-type year pages would be the cheap way to
    get them, but only Ordinary Council Meetings has one: the special
    meetings' /council-meetings/special-council-meeting/past/<year> answers
    404 for every year. So each year is read from the all-types listing,
    three pages or so, and a meeting of any other type is skipped before its
    page is fetched. Documents are on each meeting's page, so a year costs
    those listing pages and a request per Council meeting. Upcoming meetings
    are on Resolve, so the upcoming page is not read."""

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
    }
    upcoming_path = None
    first_year = 2016

    def __init__(self, owner: BaseScraper):
        super().__init__(owner.council_name, owner.state, SITE)
        self.fetcher = owner.fetcher
        self.logger = owner.logger

    def _listing_urls(self, year: int) -> list[str]:
        return [f"{self.base_url}/council-meetings/past/{year}"]

    def _summary_meeting(self, summary, listing_url, labels, year, seen):
        types = {
            self.meeting_type_of(urljoin(listing_url, link["href"]))
            for link in summary.find_all("a", href=True)
        }
        if not types & set(self.meeting_types):
            return []
        return super()._summary_meeting(summary, listing_url, labels, year, seen)
