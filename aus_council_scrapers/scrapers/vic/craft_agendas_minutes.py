"""The agendas-and-minutes table on two Victorian Craft CMS sites.

Mitchell and Bass Coast run the same SimpleGov-style Craft archive as the six
South Australian councils in `aus_council_scrapers/craft.py`: the
`when=custom&from=…&to=…` GET filter, the `/pN` pager, PDFs filed under
`/assets/agendas-minutes/{agendas,minutes,attachments}/`, and AWS WAF on
CloudFront in front. Only the row markup is theirs, and it is shared:
`table.table--agendas-minutes`, one `tr.table__row` per meeting, with the
date in `td.table__cell--meetingdate` (labelled "Date / Location" on
Mitchell and "Meeting Date" on Bass Coast, which is why it is matched by
class), the meeting type in `td[data-th="Committee"]` and the documents in
`td[data-th="Downloads"]`.

The date cell holds the date, then, where the council filled it in, a line
like "7:00 pm via livestream" or "1:00 pm at Civic Centre Council Chamber,
Wonthaggi" (the venue a link to its page). Past Bass Coast rows have the
date alone.
"""

from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.craft import (
    CraftArchiveScraper,
    CraftMeeting,
    clean_text,
    document_links,
    parse_listing_date,
    parse_listing_time,
)

_VENUE = re.compile(r"\bat\s+(.+?)(?:\s+Watch meeting)?$", re.IGNORECASE)

# "Joint Council Meeting — Hume City Council, Mitchell Shire Council and
# Whittlesea City Council": the type is before the dash. Mitchell also
# appends a status, "Community Questions and Hearings (cancelled)", which is
# not part of the type. Nearly every cancelled row has no papers and is
# skipped; the 20 May 2024 one kept its agenda.
_NAME_TAIL = re.compile(
    r"\s+[—–]\s+.*$|\s*\((?:cancelled|postponed)\)\s*$", re.IGNORECASE
)


class CraftAgendasMinutesTableScraper(CraftArchiveScraper):
    def parse_meetings(self, soup: BeautifulSoup) -> list[CraftMeeting]:
        meetings = []
        for row in soup.select("tr.table__row"):
            cell = row.select_one("td.table__cell--meetingdate")
            if cell is None:
                continue  # the header row
            when = clean_text(cell)
            date = parse_listing_date(when)
            if date is None:
                self.logger.warning(f"No date in listing row: {when!r}")
                continue

            venue_link = cell.find("a", href=re.compile(r"/venues"))
            venue_match = _VENUE.search(when)
            location = clean_text(venue_link) or (
                venue_match.group(1) if venue_match else None
            )

            downloads = row.select_one('td[data-th="Downloads"]')
            links = document_links(downloads, self.listing_url) if downloads else []
            # Attachments are left out before classification, not after. The
            # base class judges a PDF outside the agendas and minutes folders
            # by its link text when those folders leave a kind empty, and on
            # these sites the attachments folder holds other meetings'
            # papers: Mitchell's Council meeting of 19 October 2026 attaches
            # the Joint Council meeting's minutes ("Joint Council meeting
            # Minutes 7 October 2026"), which that pass would take as the
            # Council meeting's own. Across both archives since 2020 no
            # meeting's own agenda or minutes is filed in attachments, so
            # nothing is lost by it.
            links = [
                (label, url)
                for label, url in links
                if "/attachments/" not in urllib.parse.urlsplit(url).path
            ]

            meetings.append(
                CraftMeeting(
                    name=_NAME_TAIL.sub(
                        "", clean_text(row.select_one('td[data-th="Committee"]'))
                    ),
                    date=date,
                    time=parse_listing_time(when),
                    location=location,
                    links=links,
                )
            )
        return meetings
