"""MidCoast Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary Council
meetings and the Strategic Committee (a committee of the whole council) back
to 2016, and the three former councils' papers before the 2016
amalgamation, which are older than anything fetched. The filter also offers
a "DCU" type with no rows from 2020 on. Every type in range is a Council
meeting, so nothing is allowlisted.

Papers are filed under headings with every link labelled "Download PDF", so
``papers_by = "heading"``. Every meeting from 2020 has a plain "Agenda" and
"Minutes" heading; the rest—"Attachments Agenda - Corporate Services",
"Mayoral Minute" (singular), "Late Report", "Item 16.1 … Attachments",
audio and video recordings—is passed over by the base class's rules.

The site is behind Cloudflare (``server: cloudflare``) as well as the usual
OpenCities Akamai edge; the project's identifying User-Agent is served
normally, and a generic browser string got a 403 when the site was scouted.

With ``page_size`` a year is one listing request, and the filtered page
carries the full year dropdown, so one production year is that request plus
a payload per meeting: 11 for 2026.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class MidCoastScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 21 s for
    # 11 requests. Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 21

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # Measured October 2026: (pagesize=50) returns the whole year on one
    # page, and the filtered page offers every year in its dropdown.
    page_size = 50
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "mid_coast",
            "NSW",
            "https://www.midcoast.nsw.gov.au/Your-Council/Council-meetings/Agendas-and-minutes",
        )
