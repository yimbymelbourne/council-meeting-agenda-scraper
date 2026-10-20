"""Mornington Peninsula Shire—OpenCities, on `OpenCitiesMeetingsScraper`.

The one OpenCities council here that drives the listing by **form postback**
rather than the ``dlv_`` GET URL (its list is ``OC CL Public2 Meetings``).
That is history, not necessity: this scraper predates the base class, and its
cassette—recorded against the postback pager—is the regression check that
the base class still does what this scraper always did. Moving it to the GET
URL means re-recording it, which is worth doing only alongside some other
reason to.

**Unstructured documents.** Every file for a meeting—agenda, minutes,
attachment book, public notices, public question time, item attachments,
community flyers—is one flat "Related Information" list, so the papers are
picked out by their link text (``papers_by = "link_text"``).

**What this costs.** Unfiltered: one listing request per page (16 as of
September 2026) plus one payload per meeting (153), so ~170 requests and a
little under six minutes at the default 2 s ``FETCH_DELAY``. Production asks
for one year: the listing GET, the year-filter postback, one or two pager
postbacks and one payload per meeting in that year—22 requests for 2026,
measured in October 2026. No
meeting-type allowlist is applied, because the existing cassette records the
Cemetery Trust and Section 223 committee meetings too; narrowing that is a
separate change.

Location is deliberately not set. These payloads have no `meeting-address`
element—not one of the 153 meetings recorded in September 2026—and the
address appears only inside free prose that also carries rescheduling notices
and livestream instructions ("Meeting reschduled from the 4 August 2026.
Meeting was held at 6.30pm at the Municipal Offices..."). Storing a slice of
that as the location would be inventing a field, so the base class's
`meeting-address` reader finds nothing here and leaves it empty.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# The canonical listing URL, deliberately not the /About-Us/... alias recorded
# in docs/councils.md at one point. That alias answers 302, and `requests`
# downgrades a redirected POST to a GET—which silently discards the pager's
# form data and hands back page 1 every time. The council then looks like one
# that publishes only ten meetings, with nothing to suggest the pager was the
# problem.
_LISTING_URL = (
    "https://www.mornpen.vic.gov.au"
    "/The-Shire/About-our-Council/Council-meetings"
    "/Council-Committee-meeting-agendas-and-minutes"
)


@register_scraper
class MorningtonPeninsulaScraper(OpenCitiesMeetingsScraper):
    papers_by = "link_text"
    # One production year, measured Oct 2026 from a home IP: 42 s on this
    # base class (69 s on the scraper it replaced). Orders dispatch only
    # (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 42

    def __init__(self):
        super().__init__("mornington_peninsula", "VIC", _LISTING_URL)
