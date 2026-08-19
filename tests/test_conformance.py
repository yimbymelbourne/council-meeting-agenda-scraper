"""Gate: no scraper may record a fixture that violates the invariants.

This runs against the recorded fixtures rather than re-running the scrapers.
`scraper_test.py` already asserts that a scraper reproduces its fixture
exactly, so checking the fixture checks the output — and it costs
milliseconds instead of a full replay.

Only invariants are enforced. Coverage gaps (too few years, no minutes) are
reported by `scripts/scorecard.py` and deliberately do not fail the build:
an unfinished scraper is not a broken one, and a red build that everyone
learns to ignore protects nothing.
"""

import glob
import json
import os

import pytest

from aus_council_scrapers.conformance import assess
from tests.known_broken import OUTPUT_BROKEN


def _fixtures():
    for path in sorted(glob.glob("tests/test-cases/*-result.json")):
        slug = os.path.basename(path).replace("-result.json", "")
        marks = []
        if slug in OUTPUT_BROKEN:
            marks.append(pytest.mark.xfail(strict=True, reason=OUTPUT_BROKEN[slug]))
        yield pytest.param(slug, path, marks=marks, id=slug)


@pytest.mark.parametrize("slug,path", list(_fixtures()))
def test_scraper_output_is_well_formed(slug: str, path: str):
    with open(path) as f:
        meetings = json.load(f)
    if isinstance(meetings, dict):
        meetings = [meetings]

    result = assess(slug, meetings)

    assert not result.invariants, (
        f"{slug}: {'; '.join(result.invariants)}\n"
        f"({result.meetings} meetings, {result.span})\n\n"
        f"These are defects in the recorded output, not coverage gaps. "
        f"Run `python scripts/scorecard.py` for the full picture."
    )


def test_known_broken_lists_have_no_stale_entries():
    """Every entry must correspond to a real fixture, so the lists cannot
    accumulate names of scrapers that no longer exist."""
    from tests.known_broken import REPLAY_BROKEN

    recorded = {
        os.path.basename(p).replace("-result.json", "")
        for p in glob.glob("tests/test-cases/*-result.json")
    }
    for name, listing in (("OUTPUT_BROKEN", OUTPUT_BROKEN), ("REPLAY_BROKEN", REPLAY_BROKEN)):
        unknown = set(listing) - recorded
        assert not unknown, f"{name} names scrapers with no fixture: {sorted(unknown)}"
