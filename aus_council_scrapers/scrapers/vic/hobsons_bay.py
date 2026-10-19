"""Hobsons Bay City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing moved to ``/Council/Council-meetings/Minutes-and-agendas``; the
mixed-case address in docs/councils.md now 302s here. One list
(``OC CL Public Meetings``) holds every meeting.

Papers are filed under headings with every link labelled "Download PDF", so
``papers_by = "heading"``. The headings seen (October 2026): "Agenda",
"Resolutions" / "Council Meeting Resolutions" (a summary of decisions—not
the minutes), and "Confirmed Minutes", "Unconfirmed Minutes", or either with
the date appended. Confirmed minutes win when a meeting lists both.

The council says it keeps only the last four years online, and it does: the
listing starts in October 2022 although its year filter offers 2012 onwards.
That window rolls, so a re-recorded cassette will lose its oldest meetings as
the council deletes them—that is the council, not a regression.

Meeting types are only Council and Special meetings. One production year is
about a dozen requests.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class HobsonsBayScraper(OpenCitiesMeetingsScraper):
    list_name = "OC CL Public Meetings"
    papers_by = "heading"

    def __init__(self):
        super().__init__(
            "hobsons_bay",
            "VIC",
            "https://www.hobsonsbay.vic.gov.au/Council/Council-meetings/Minutes-and-agendas",
        )
