"""Tests for `InfoCouncilScraper.tidy_meeting_rows`.

The cassettes show the flag's output for seven councils but not the rule it
enforces: a supplementary paper is never a meeting's agenda. InfoCouncil gives
each supplementary agenda a grid row of its own, so without the flag it comes
out as a second meeting whose "agenda" is the supplementary—and the venue
held in the committee cell's <span> runs into every meeting name.
"""

import pytest

from aus_council_scrapers.base import InfoCouncilScraper
from tests.test_infocouncil_grid import LISTING_URL, PDF, _AnyYear, _grid, _row


class _Tidy(InfoCouncilScraper):
    tidy_meeting_rows = True

    def __init__(self):
        super().__init__("example", "QLD", "https://example.qld.gov.au", LISTING_URL)


def _scrape(rows: str):
    scraper = _Tidy()
    scraper.fetcher = _AnyYear(_grid(rows))
    return scraper.scraper()


PARENT = _row(
    "Council <br/>",
    "14 Oct 2026",
    PDF.format(href="CO_20261014_AGN_2431_AT.PDF"),
    PDF.format(href="CO_20261014_MIN_2431_AT.PDF"),
)


@pytest.mark.parametrize(
    "committee, agenda_file",
    [
        # Redland: marker plus upload stamp.
        ("Council - Supplementary uploaded 12/10/2026 16:27", "CO_AGN_AT_SUP.PDF"),
        # Vincent's wording for the same thing.
        ("Council Late Items", "CO_AGN_AT_SUP.PDF"),
        # Row text that says nothing; only the filename gives it away.
        ("Council", "CO_20261014_AGN_2431_AT_SUP_27305.PDF"),
        # Ipswich: the chair's annotated copy of the agenda, on its own row.
        ("Council", "CO_20261014_AGN_2431_AT_CHAIRMANS_EXTRA.PDF"),
    ],
)
def test_a_supplementary_row_folds_into_its_meeting(committee, agenda_file):
    results = _scrape(
        PARENT + _row(committee, "14 Oct 2026", PDF.format(href=agenda_file), "")
    )

    assert len(results) == 1
    meeting = results[0]
    assert meeting.name == "Council"
    assert meeting.location == "Town Hall"
    assert meeting.agenda_url.endswith("CO_20261014_AGN_2431_AT.PDF")
    assert meeting.minutes_url.endswith("CO_20261014_MIN_2431_AT.PDF")


def test_a_supplementary_row_without_its_parent_is_not_a_meeting():
    """Redland's "Previously Confidential Information" rows are only ever
    supplementary papers; there is no agenda to report."""
    assert (
        _scrape(
            _row(
                "Previously Confidential Information - Supplementary",
                "16 Dec 2020",
                PDF.format(href="PCICC_16122020_AGN_SUP.pdf"),
                "",
            )
        )
        == []
    )
