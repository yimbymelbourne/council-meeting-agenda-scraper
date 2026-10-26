"""Borough of Queenscliffe—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Special meetings of
Council and the Planning Review Meeting (its planning body) from 2016, with
a year filter. Those are all the meeting types, so nothing is filtered out.
Older years (2009–2015) are only in per-year ZIP archives on the same page,
which this does not read.

The payloads come in three layouts, which is why ``papers_by = "search"``:

* **To mid-2023**, folders: a "Minutes" and an "Agenda" folder whose files
  are titled "October 2022 Ordinary Meeting Agenda", followed by
  "Appendix N" books.
* **Mid to late 2023**, a mix: headed sections ("Agenda", "Agenda Ordinary
  Meeting of Council 25 October 2023") beside folders (8 November 2023
  files its minutes in a "Minutes" folder inside a "Reports" folder).
* **Late 2023 on**, one section headed "Ordinary Meeting of Council 26
  August 2026 - Minutes", whose first PDF is the minutes, with each item's
  attachments in folders inside it. 13 December 2023's heading is just
  "Ordinary Meeting of Council 13 December 2023"; its file is named as
  minutes, which search mode goes by. The 12 June 2024 Planning Review
  Meeting's is "Planning Review Meeting 12 June 2024" and its file names
  neither paper; its first page says "Agenda", so with
  ``title_heading_agenda`` a heading that is just the meeting's title, over
  a file that names neither, is the agenda.

**From late 2023 the agenda is replaced by the minutes.** The payload then
holds only the minutes, so meetings from November 2023 on are minutes-only:
no agenda for any 2024–2026 Council meeting was found (checked 20 October
2026); the 12 June 2024 Planning Review Meeting has its agenda. An
upcoming meeting may show its agenda until the minutes replace it; none
was listed to check.

The listing renamed its meeting types in late 2023, from "Ordinary
Meeting" and "Special Meeting" to "Ordinary Council Meeting" and "Special
Council Meeting", and 27 September 2023 is listed under both: once with
its agenda, once with its minutes. Names are normalised to the current
ones (`meeting_name`) so those two rows merge into one meeting.

28 January 2026 is listed twice as well, each row with the same minutes (the
same 71-page PDF, byte for byte) at a different URL, which the base class
cannot merge because the URLs differ. Only the first is kept (`scraper`).

robots.txt disallows only some Home, Extras and footer pages. The site is
behind Akamai; the project fetcher gets 200 where the scout found a bare
request refused.

One production year is 13 requests: the listing filtered to that year at
``page_size`` 50 (12 rows in 2026), then a payload per meeting.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

_OLD_NAME = re.compile(r"^(ordinary|special)\s+meeting$", re.IGNORECASE)


@register_scraper
class QueenscliffeScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 25 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 25

    list_name = "OC CL Public Meetings"
    papers_by = "search"
    title_heading_agenda = True
    # The busiest year is 17 rows: one listing page a year.
    page_size = 50
    # The year-filtered page offers every year in its dropdown (checked
    # 20 October 2026), so production skips the bare first page.
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "queenscliffe",
            "VIC",
            "https://www.queenscliffe.vic.gov.au/Your-Council/Council-meetings/Minutes-and-agendas",
        )

    def meeting_name(
        self, row: ListingRow, content: BeautifulSoup, papers: dict[str, str]
    ) -> str:
        name = row.meeting_type or self.default_name
        match = _OLD_NAME.match(name.strip())
        if match:
            return f"{match.group(1).title()} Council Meeting"
        return name

    def scraper(self) -> list[ScraperReturn]:
        results = []
        seen: set[tuple] = set()
        for record in super().scraper():
            # A second minutes-only record of the same meeting: the same
            # minutes listed twice (see the module docstring).
            key = (record.name, record.date)
            if not record.agenda_url and key in seen:
                self.logger.info(
                    f"{record.date} {record.name}: listed twice; kept the first"
                )
                continue
            if not record.agenda_url:
                seen.add(key)
            results.append(record)
        return results
