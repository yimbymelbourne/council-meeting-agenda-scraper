import json
import os

import pytest

from aus_council_scrapers.base import (
    SCRAPER_REGISTRY,
    BaseScraper,
    DefaultFetcher,
    ScraperReturn,
)
from tests.cassette import (
    PlaybackFetcher,
    RecordingFetcher,
    cassette_paths,
    should_record,
)


def _load_expected(result_path: str) -> list[ScraperReturn]:
    with open(result_path, "r") as f:
        data = json.load(f)
    # Cassettes cut before scrapers returned lists hold a single object.
    if isinstance(data, dict):
        data = [data]
    return [ScraperReturn.from_dict(r) for r in data]


def _assert_matches(
    result: list[ScraperReturn], expected: list[ScraperReturn], slug: str
):
    """Compare strictly, and say precisely what moved when it fails."""
    rerecord = (
        f"If this change is correct, re-record with:\n"
        f"  RECORD={slug} poetry run pytest tests/scraper_test.py -k {slug}"
    )

    if len(result) != len(expected):
        raise AssertionError(
            f"{slug}: scraper returned {len(result)} meeting(s), cassette records "
            f"{len(expected)}.\n\n{rerecord}"
        )

    for i, (got, want) in enumerate(zip(result, expected)):
        if got != want:
            raise AssertionError(
                f"{slug}: meeting {i} differs from the cassette.\n"
                f"  recorded: {json.dumps(want.to_dict(), indent=2)}\n"
                f"  returned: {json.dumps(got.to_dict(), indent=2)}\n\n{rerecord}"
            )


def _replay(scraper: BaseScraper, slug: str, result_path: str, replay_path: str):
    expected = _load_expected(result_path)
    with open(replay_path, "r") as f:
        replay_data = json.load(f)

    scraper.fetcher = PlaybackFetcher(replay_data, slug)
    result = scraper.scraper()
    _assert_matches(result, expected, slug)


def _record(scraper: BaseScraper, slug: str, result_path: str, replay_path: str):
    recorder = RecordingFetcher(DefaultFetcher())
    scraper.fetcher = recorder
    try:
        result = scraper.scraper()
    finally:
        recorder.close()

    with open(replay_path, "w") as f:
        json.dump(recorder.replay_data, f)
    with open(result_path, "w") as f:
        json.dump([r.to_dict() for r in result], f, indent=2)

    if not result:
        raise AssertionError(
            f"{slug}: recorded a live run that returned zero meetings. A scraper "
            f"that finds nothing is broken — the cassette was still written so you "
            f"can inspect what the site returned."
        )


@pytest.mark.parametrize(
    "scraper_instance", SCRAPER_REGISTRY.values(), ids=SCRAPER_REGISTRY.keys()
)
def test_scraper(scraper_instance: BaseScraper):
    slug = scraper_instance.council_name
    result_path, replay_path = cassette_paths(slug)
    have_cassette = os.path.exists(result_path) and os.path.exists(replay_path)

    if have_cassette and not should_record(slug):
        _replay(scraper_instance, slug, result_path, replay_path)
    else:
        _record(scraper_instance, slug, result_path, replay_path)
