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


def test_every_recorded_scraper_appears_in_the_council_list():
    """A slug that differs between the scraper and docs/councils.md makes the
    scorecard count one council twice — once as recorded, once as never
    started. Three slugs had drifted this way: a misspelled 'port_philip', a
    'penrith' that the scraper called 'penrith_city', and a Randwick scraper
    with 431 meetings and no row at all.
    """
    import re

    tracked = set()
    for line in open("docs/councils.md"):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"[a-z0-9_]+", cells[-1]):
            tracked.add(cells[-1])

    recorded = {
        os.path.basename(p).replace("-result.json", "")
        for p in glob.glob("tests/test-cases/*-result.json")
    }
    missing = sorted(recorded - tracked)
    assert not missing, (
        f"these scrapers have fixtures but no row in docs/councils.md: {missing}. "
        f"Add a row, or align the slug so the two agree."
    )


@pytest.mark.skipif(
    os.environ.get("GITHUB_REF") != "refs/heads/main",
    reason="status.md is maintained on main only; it is expected to lag on a branch",
)
def test_status_doc_is_current():
    """docs/status.md is what a developer reads to see which councils work, so
    a stale one is worse than none. This catches the regeneration workflow
    failing silently.

    Deliberately main-only. A branch that re-records a scraper changes the
    coverage this file reports, and enforcing it there would force every such
    PR to regenerate and commit status.md — putting all of them back in
    conflict over one file, which is the whole reason generation happens after
    merge rather than in the PR.
    """
    import subprocess
    import sys

    if not os.path.exists("docs/status.md"):
        pytest.skip("docs/status.md has not been generated yet")

    generated = subprocess.run(
        [sys.executable, "scripts/scorecard.py", "--markdown"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert generated == open("docs/status.md").read().strip(), (
        "docs/status.md is out of date. Regenerate it with:\n"
        "  python scripts/scorecard.py --markdown > docs/status.md"
    )
