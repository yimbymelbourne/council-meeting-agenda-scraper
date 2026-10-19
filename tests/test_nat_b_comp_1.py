"""The production fetch bound for the five councils read from two platforms.

Dungog and Gwydir (Resolve plus their OpenCities listing), East Pilbara and
Alice Springs (Resolve plus their CouncilConnect module) and Nannup
(DocsPublished plus its CouncilConnect module) each join two sources at the
day the council moved. Cassettes are recorded unfiltered, so the replay test
proves the whole history parses but says nothing about what one production
night costs.

Only Nannup's production year can be replayed: Resolve asks for one date
range per run of wanted years, so a filtered run asks the API for a URL the
unfiltered recording never made. For the four Resolve councils these replay
the years before the move instead, which read the archive alone, and check
the filtered run finds every meeting of that year from the archive's host.
"""

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

REQUEST_BUDGET = 20

# The host each council's archive lives on.
ARCHIVE_HOSTS = {
    "DungogScraper": "www.dungog.nsw.gov.au",
    "GwydirScraper": "www.gwydir.nsw.gov.au",
    "EastPilbaraScraper": "www.eastpilbara.wa.gov.au",
    "AliceSpringsScraper": "www.alicesprings.nt.gov.au",
    "NannupScraper": "www.nannup.wa.gov.au",
}


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _replay(class_name: str, year: int):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        fetcher = _Counting(json.load(f), scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    try:
        with clock.frozen(fetcher.recorded_date):
            results = scraper.scraper()
    finally:
        del scraper.years_filter
    return fetcher, recorded, results


def _in_year(meetings: list[dict], year: int) -> list[dict]:
    return sorted(
        (m for m in meetings if m["date"].startswith(str(year))),
        key=lambda m: (m["date"], m["name"], m["agenda_url"] or ""),
    )


def test_nannups_production_year_stays_in_budget_and_loses_nothing():
    # 2026 needs both sources: DocsPublished from 23 July, the module before.
    year = 2026
    fetcher, recorded, results = _replay("NannupScraper", year)
    assert len(fetcher.urls) <= REQUEST_BUDGET, fetcher.urls
    got = _in_year([r.to_dict() for r in results], year)
    assert got == _in_year(recorded, year)
    assert {"docspublished", "nannup.wa.gov.au"} <= {
        "docspublished" if "docspublished" in m["webpage_url"] else "nannup.wa.gov.au"
        for m in got
    }


@pytest.mark.parametrize(
    "class_name, year",
    [
        ("DungogScraper", 2022),
        ("EastPilbaraScraper", 2023),
        ("AliceSpringsScraper", 2021),
        ("GwydirScraper", 2025),
        ("NannupScraper", 2024),
    ],
)
def test_a_year_before_the_move_comes_from_the_archive_alone(class_name, year):
    fetcher, recorded, results = _replay(class_name, year)
    got = _in_year([r.to_dict() for r in results], year)
    assert got == _in_year(recorded, year)
    assert all(ARCHIVE_HOSTS[class_name] in m["webpage_url"] for m in got)


def _failing_archive_read(monkeypatch, failing_types: dict[str, str]):
    """Make CouncilConnectArchive.read raise for one set of meeting types,
    as a listing that times out would."""
    from aus_council_scrapers.councilconnect import CouncilConnectArchive

    real_read = CouncilConnectArchive.read

    def read(self, *args, **kwargs):
        if self.meeting_types == failing_types:
            raise RuntimeError("listing timed out")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(CouncilConnectArchive, "read", read)


@pytest.mark.parametrize("which", ["_UNMOVED_TYPES", "_MOVED_TYPES"])
def test_alice_springs_fails_when_its_only_source_for_a_year_fails(monkeypatch, which):
    # The full range, as a re-recording asks for it: Resolve has meetings, so
    # `ResolveScraper.scraper` would keep them and drop the archive's with a
    # warning. The module is the only source of the two bodies that never
    # moved and of every Council meeting before 2025, so either read failing
    # must fail the council instead.
    from aus_council_scrapers.resolve import SoleSourceFailed
    from aus_council_scrapers.scrapers.nt import alice_springs

    _failing_archive_read(monkeypatch, getattr(alice_springs, which))
    scraper = SCRAPER_REGISTRY["AliceSpringsScraper"]
    _, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        scraper.fetcher = PlaybackFetcher(json.load(f), scraper.council_name)
    with clock.frozen(scraper.fetcher.recorded_date), pytest.raises(SoleSourceFailed):
        scraper.scraper()


def test_alice_springs_archive_meetings_carry_no_time():
    # The module's time field says 6:00 PM on every timed entry, which the
    # agendas contradict, so archive meetings are emitted without one.
    _, _, results = _replay("AliceSpringsScraper", 2024)
    assert results and all(r.time is None for r in results)
