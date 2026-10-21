"""Production-shaped runs of the D-7 scrapers, replayed from their cassettes.

Cassettes are recorded unfiltered, so scraper_test.py never sees what a
production night does: one `--years` year. Three things can go wrong there
that the replay cannot catch:

- a per-meeting scraper that ignores `years_filter` returns the right
  meetings but fetches every year's pages, which is charged against the
  shared 600 s budget;
- a Barcoo folder postback that fails in a one-year run must fail the
  council, not report that year's meetings without their agendas or newest
  minutes;
- Mount Marshall's dates page moving on to next year must fail the run, not
  quietly drop every ordinary meeting of this one.
"""

from __future__ import annotations

import json

import pytest
import requests

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nt.belyuen import BelyuenScraper
from aus_council_scrapers.scrapers.qld.barcoo import BarcooScraper
from aus_council_scrapers.scrapers.wa.kent import KentScraper
from aus_council_scrapers.scrapers.wa.mount_marshall import MountMarshallScraper
from aus_council_scrapers.scrapers.wa.nungarin import NungarinScraper
from aus_council_scrapers.scrapers.wa.woodanilling import WoodanillingScraper
from tests.cassette import PlaybackFetcher
from tests.replay_cost import CountingPlayback, load_cassette, meetings_in, recorded_date

_YEAR = 2025


class _PostbackPlayback(CountingPlayback):
    """Replays Barcoo's postbacks by what they ask for, not their form state.

    Each postback carries the __VIEWSTATE of the page before it, so a run
    that opens fewer folders than the recording sends state the cassette
    never saw. The portal answers by event target and argument, so that is
    what is matched here.
    """

    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self._postbacks = {}
        for key, value in replay_data:
            if key and key[0] == "requests" and key[2] == "POST":
                data = json.loads(key[3])["data"]
                self._postbacks[(data["__EVENTTARGET"], data["__EVENTARGUMENT"])] = value

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if method != "POST":
            return super().fetch_with_requests(url, method, **kwargs)
        self.requested.append(url)
        data = kwargs["data"]
        return self._postbacks[(data["__EVENTTARGET"], data["__EVENTARGUMENT"])]


@pytest.mark.parametrize(
    "slug, scraper_class",
    [
        ("kent", KentScraper),
        ("woodanilling", WoodanillingScraper),
        ("belyuen", BelyuenScraper),
        ("barcoo", BarcooScraper),
    ],
)
def test_one_year_returns_that_year_and_fetches_less(slug, scraper_class):
    replay, expected = load_cassette(slug)
    full_run = sum(1 for key, _ in replay if key and key[0] == "requests")

    scraper = scraper_class()
    playback = _PostbackPlayback if slug == "barcoo" else CountingPlayback
    scraper.fetcher = playback(replay, slug)
    scraper.years_filter = [_YEAR]
    with clock.frozen(recorded_date(replay)):
        result = [r.to_dict() for r in scraper.scraper()]

    wanted = meetings_in(expected, _YEAR)
    assert wanted, f"{slug}: the recording has no {_YEAR} meetings to compare"
    assert meetings_in(result, _YEAR) == wanted
    assert len(result) == len(wanted)
    # A year is a small share of six-plus years of pages.
    requests_made = len(scraper.fetcher.requested)
    assert requests_made < full_run / 2, f"{slug}: {requests_made} requests for one year, {full_run} for all"


class _FolderFails(_PostbackPlayback):
    """Replays the portal; the one folder named fails."""

    def __init__(self, replay_data, slug, failing):
        super().__init__(replay_data, slug)
        self._failing = failing

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if (kwargs.get("data") or {}).get("__EVENTARGUMENT") == self._failing:
            raise requests.ConnectionError(f"folder {self._failing} refused")
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize("failing", ["s2026", "s2026\\Unconfirmed Minutes"])
def test_barcoo_raises_when_any_wanted_folder_fails(failing):
    replay, _ = load_cassette("barcoo")
    scraper = BarcooScraper()
    scraper.fetcher = _FolderFails(replay, "barcoo", failing)
    scraper.years_filter = [2026]
    with clock.frozen(recorded_date(replay)), pytest.raises(requests.ConnectionError):
        scraper.scraper()


def test_barcoo_document_urls_are_stable_across_sessions():
    # The portal's per-session hash is replaced, so a re-run tomorrow emits
    # the same URL for the same document.
    _, expected = load_cassette("barcoo")
    urls = [m[k] for m in expected for k in ("agenda_url", "minutes_url") if m[k]]
    assert urls and all(url.endswith("/" + "0" * 32) for url in urls)


class _DatesMovedOn(PlaybackFetcher):
    """Replays Mount Marshall with its dates page rolled over to 2027."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        page = super().fetch_with_requests(url, method, **kwargs)
        if "meeting-dates" in url:
            page = page.replace(" 2026 at ", " 2027 at ")
        return page


def test_mount_marshall_fails_when_the_dates_page_has_moved_on():
    # In December the page may list next year's dates while this year's
    # November and December papers are still current; a one-year run must
    # fail rather than report only the special meetings.
    replay, _ = load_cassette("mount_marshall")
    scraper = MountMarshallScraper()
    scraper.fetcher = _DatesMovedOn(replay, "mount_marshall")
    scraper.years_filter = [2026]
    with clock.frozen(recorded_date(replay)), pytest.raises(RuntimeError, match="cannot be dated"):
        scraper.scraper()


@pytest.mark.parametrize("year, empty_is_an_error", [(2018, True), (2027, False)])
def test_an_empty_result_fails_unless_the_year_has_not_started(year, empty_is_an_error):
    # Nungarin's table starts in 2019. A past year with nothing is a broken
    # page, and [] would be recorded as a successful scrape; a year that has
    # not begun legitimately has nothing yet.
    replay, _ = load_cassette("nungarin")
    scraper = NungarinScraper()
    scraper.fetcher = PlaybackFetcher(replay, "nungarin")
    scraper.years_filter = [year]
    with clock.frozen(recorded_date(replay)):
        if empty_is_an_error:
            with pytest.raises(RuntimeError, match="found no meetings"):
                scraper.scraper()
        else:
            assert scraper.scraper() == []
