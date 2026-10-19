"""City of Onkaparinga—OpenCities, on `OpenCitiesMeetingsScraper`.

``/Council/Council-and-committees/Agendas-and-Minutes`` is a hub page linking
one listing per body. Two are read:

* **Council meetings** (``CoO CL Public Meetings - Council 2``)—ordinary
  and special Council meetings, from 2014.
* **Council Assessment Panel** (``CoO CL Public Meetings - CAP 2``)—the
  planning body.

The Audit and Risk, Chief Executive Performance Management, "Other" and
Elected Member session listings are neither Council nor planning bodies, and
each listed meeting costs a payload request, so they are left out.

The year filter here has a blank first option instead of "Any Year"; the base
class recognises it by its options being years.

Papers are filed under headings, so ``papers_by = "heading"``. Beside
"Agenda" and "Minutes", a meeting's payload carries deputation requests,
separate-cover reports ("Item 10.12 ..."), "Summary of councillor questions"
and "Part release" confidential items, each under its own heading; heading
mode reads only the two.

In October 2026 the newest Council row was the 13 October meeting, already
held, so whether a meeting is listed before its agenda is out was not seen.
One production year is the filtered listing pages of each body (the first
also gives the year dropdown, so no unfiltered page is fetched) and one
payload per meeting: 29 requests and 58 s for 2026, measured in October
2026, 26 of them payloads for Council and CAP meetings, so there is nothing
left to cut.
"""

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import Listing, OpenCitiesMeetingsScraper

_BASE = (
    "https://www.onkaparingacity.com/Council/Council-and-committees/Agendas-and-Minutes"
)


@register_scraper
class OnkaparingaScraper(OpenCitiesMeetingsScraper):
    list_name = "CoO CL Public Meetings - Council 2"
    papers_by = "heading"
    # Each year-filtered page carries the full year dropdown, so production
    # skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__("onkaparinga", "SA", f"{_BASE}/Council-meetings")

    def extra_listings(self, first_page_html: str) -> list[Listing]:
        return [
            Listing(
                f"{_BASE}/Council-Assessment-Panel", "CoO CL Public Meetings - CAP 2"
            )
        ]
