"""Isaac drops papers whose filename names another meeting's date, and must
still say so when that leaves a meeting with nothing.

`IsaacScraper.row_papers` removes those links before picking papers, and the
base class's `build_return` counts the payload's PDFs to warn about a meeting
whose every file was rejected. If the removal happened on the payload itself,
a year typo in every filename would drop the meeting with no warning at all.
The recorded fixture has no such meeting (13 May 2025 keeps its agenda), so
replay cannot catch that regression.
"""

import logging

from bs4 import BeautifulSoup

from aus_council_scrapers.opencities import ListingRow
from aus_council_scrapers.scrapers.qld.isaac import IsaacScraper

_FILES = "https://www.isaac.qld.gov.au/files/assets/public/v/1/council-meetings"


def test_a_meeting_whose_every_paper_names_another_date_is_warned_about(caplog):
    # Both filenames say 2024; the row is the 2025 meeting.
    payload = BeautifulSoup(
        f"""
        <div class="meeting-attachments"><ul>
          <li><a href="{_FILES}/agenda-ordinary-meeting-26-february-2024.pdf"
            >PUBLIC_Agenda___Ordinary_Meeting___Wednesday_26_February_2024.pdf</a></li>
          <li><a href="{_FILES}/minutes-ordinary-meeting-26-february-2024.pdf"
            >Confirmed_Minutes___Ordinary_Meeting___Wednesday_26_February_2024.pdf</a></li>
        </ul></div>""",
        "html.parser",
    )
    row = ListingRow(
        "26 February 2025",
        "Ordinary Meeting",
        "00000000-0000-0000-0000-000000000000",
        "https://www.isaac.qld.gov.au/Your-Council/Council-Meetings",
    )

    with caplog.at_level(logging.WARNING):
        record = IsaacScraper().build_return(payload, row)

    assert record is None
    assert "no agenda or minutes among its 2 PDFs" in caplog.text
