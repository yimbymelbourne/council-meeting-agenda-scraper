"""The meeting date each listed InfoCouncil council emits is the date
InfoCouncil itself writes into the document filenames.

InfoCouncil names every paper <committee>_<date>_AGN|MIN_..., and that date is
the meeting's. Checking the emitted date against it catches the failure the
replay comparison cannot: a fixture re-recorded with a misread date. Maranoa
is the case that motivates it—its grid writes 9/04/2026, and dateutil
without dayfirst reads that as 4 September, which a re-record would happily
enshrine. The check goes through `cleaned_date`, the value the adapter
actually publishes, not the raw string.
"""

import datetime
import json
import pathlib
import re

import pytest

from aus_council_scrapers.base import ScraperReturn

FIXTURES = pathlib.Path(__file__).parent / "test-cases"

# Coorow writes the date year-first (OCM_20261021_...); the rest day-first.
FILENAME_DATE_FORMAT = {
    "maroondah": "%d%m%Y",
    "wangaratta": "%d%m%Y",
    "southern_downs": "%d%m%Y",
    "maranoa": "%d%m%Y",
    "broome": "%d%m%Y",
    "esperance": "%d%m%Y",
    "coorow": "%Y%m%d",
}

FILENAME_DATE = re.compile(r"/[A-Z]+_(\d{8})_")


@pytest.mark.parametrize("slug", sorted(FILENAME_DATE_FORMAT))
def test_meeting_date_matches_the_document_filename(slug):
    meetings = json.loads((FIXTURES / f"{slug}-result.json").read_text())
    assert meetings, f"{slug} fixture is empty"

    mismatches = []
    for record in meetings:
        meeting = ScraperReturn.from_dict(record)
        for url in (meeting.agenda_url, meeting.minutes_url):
            match = FILENAME_DATE.search(url or "")
            if not match:
                continue
            filed = datetime.datetime.strptime(
                match.group(1), FILENAME_DATE_FORMAT[slug]
            ).date()
            if filed != meeting.cleaned_date:
                mismatches.append((meeting.name, meeting.date, url))

    assert not mismatches
