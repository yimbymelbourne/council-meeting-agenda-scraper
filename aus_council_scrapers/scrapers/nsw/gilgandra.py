"""Gilgandra Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary
meetings from 2013, upcoming ones included, with a year filter. Those are
the only two meeting types, so nothing is allowlisted.

Papers are one flat "Related Information" list, so ``papers_by =
"link_text"``. The agenda is the business paper—"15 September 2026 -
Business Paper", "16-December-2025-Business-Paper-Open.pdf"—which the base
class reads as the agenda; the minutes are "15 September 2026 - Minutes" or
"...-Minutes-Open.pdf". Recent meetings carry only the business paper until
the minutes are added. Meeting recordings (.mp3, YouTube) share the list.

Two meetings label the agenda with nothing but the meeting—"15-September-
2020-Open.pdf", "2-February-2021-Extraordinary-Meeting-open.pdf"—beside a
file that says "Minutes"; with ``title_only_agenda`` the base class takes
that file as the agenda.

The year filter can miss a meeting: 20 October 2026, with its business
paper, was on the bare listing but on no year's page (checked 20 October
2026), so ``bare_page_rows`` also reads the bare first page—the ten newest
rows—and keeps any row the year pages left out.

One production year is 15 requests: the bare listing, the listing filtered
to that year (12 meetings in 2026, 13 with the untagged one) and a payload
per meeting.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class GilgandraScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 29 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 29

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    title_only_agenda = True
    # The busiest year since 2020 is 13 meetings: one listing page a year.
    page_size = 50
    # The bare page is fetched for its rows anyway, so it is also where the
    # year dropdown is read; a year-filtered first page would save nothing.
    bare_page_rows = True

    def __init__(self):
        super().__init__(
            "gilgandra",
            "NSW",
            "https://www.gilgandra.nsw.gov.au/Your-Council/About-Council/Council-Meetings",
        )
