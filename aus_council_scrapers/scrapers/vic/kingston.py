"""City of Kingston—OpenCities, on `OpenCitiesMeetingsScraper`.

Like Frankston, Kingston splits past and upcoming meetings into two lists
(``OC CL Public Past Meetings`` and ``OC CL Public Upcoming Meetings``), and a
meeting's agenda first appears on the upcoming one—the payload says it "will
be available online from 5pm on the Thursday before the meeting". Both URLs
are stable.

Papers are filed under headings—``<h3>Agenda</h3>``, ``<h3>Minutes</h3>``—
with every link labelled "Download PDF", so ``papers_by = "heading"``. The
headings need care, and the base class's heading rules were written against
these:

* "Agenda - reports" beside "Agenda - appendices" (May 2026): the reports are
  the agenda, the appendices are an attachment book.
* "Minutes relating to item 15.2 - CEO Employment Matters" beside "Minutes"
  (June 2026): a confidential item's minutes, not the meeting's.
* That section nests a "Related Information" list linking "View minutes of
  30 March 2026 Special Council Meeting"—another meeting's paper—which is
  why heading mode ignores those lists wherever papers have headings.
* The special meetings of March and April 2020 qualify the word instead:
  "Agenda 6:30pm", "Minutes 7pm COVID 19", "Minutes Property Matter". Those
  count, but a plain "Agenda" on the same meeting wins over "Agenda Property
  Matter".
* The 25 July 2022 Council Meeting has no headings at all, only the Related
  Information list with the agenda and minutes labelled by filename; heading
  mode reads such a payload by link text instead.

The 13 November 2024 statutory meeting is listed twice, once with its agenda
and once with its minutes; the base class merges the two rows into one record.

Meeting types are Council, Special Council, Council (Statutory) and Planning
Committee meetings—all council or planning bodies, so nothing is
allowlisted. Some Planning Committee rows carry no papers at all (every one in
late 2025); they cost a payload request each and are skipped. Planning
Committee is kept anyway because it is a planning body, which is what this
project watches.

The listing reaches back to January 2018; 2020 onwards is fetched. One
production year is about 20 requests (21 for 2026, measured in October 2026).
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import Listing, OpenCitiesMeetingsScraper

_BASE_URL = "https://www.kingston.vic.gov.au/council/your-council/council-meetings"


@register_scraper
class KingstonScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 40 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 40

    list_name = "OC CL Public Past Meetings"
    papers_by = "heading"

    def __init__(self):
        super().__init__("kingston", "VIC", f"{_BASE_URL}/agendas-and-minutes")

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            Listing(
                f"{_BASE_URL}/upcoming-council-meetings",
                "OC CL Public Upcoming Meetings",
            )
        ]
