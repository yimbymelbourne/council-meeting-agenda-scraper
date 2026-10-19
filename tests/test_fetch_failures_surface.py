"""A fetch failure must reach the adapter as a failed council.

Requests now time out instead of hanging, which only helps if the timeout
gets reported. run_scraper reports a returned [] as `ok: true` with 0
meetings, and council-alerts records that as a successful scrape, so a base
class that catches the exception and returns [] turns a stalled host into a
council that silently stopped having meetings. These tests pin the two base
classes that used to do exactly that, plus the cleanup for a scraper the
adapter abandons.
"""

import os
import subprocess
import time

import pytest
import requests

from aus_council_scrapers.base import (
    DefaultFetcher,
    DocsPublishedScraper,
    InfoCouncilScraper,
)
from aus_council_scrapers.main import run_scraper
from tests.cassette import PlaybackFetcher

LISTING_URL = "https://example.infocouncil.biz/"

GRID = """
<html><body><table id="grdMenu"><tbody>
  <tr>
    <td class="bpsGridCommittee">Ordinary Council Meeting<span>Town Hall</span></td>
    <td class="bpsGridDate">12 March 2026 7:00 PM</td>
    <td class="bpsGridAgenda"><a class="bpsGridPDFLink" href="a.PDF">PDF</a></td>
    <td class="bpsGridMinutes"></td>
  </tr>
</tbody></table></body></html>
"""


class _Fetcher(PlaybackFetcher):
    """Serve `pages` by URL; raise `failure` for anything else."""

    def __init__(self, pages, failure):
        super().__init__([])
        self._pages = pages
        self._failure = failure

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url in self._pages:
            return self._pages[url]
        raise self._failure


class _InfoCouncil(InfoCouncilScraper):
    def __init__(self):
        super().__init__("example", "NSW", "https://example.nsw.gov.au", LISTING_URL)


class _DocsPublished(DocsPublishedScraper):
    publishing_slug = "example"

    def __init__(self):
        super().__init__("example", "NSW")


def _adapter_result(scraper, years):
    return run_scraper(scraper, adapter_mode=True, skip_pdf=True, years=years)


def test_infocouncil_fails_the_council_when_its_one_year_times_out():
    """Production asks for one year, so one timeout is the whole council."""
    scraper = _InfoCouncil()
    scraper.fetcher = _Fetcher({}, requests.Timeout("read timed out"))

    result = _adapter_result(scraper, [2026])

    assert result["ok"] is False
    assert result["council"] == "example"


def test_infocouncil_keeps_the_years_that_loaded():
    """A full-history walk asks for years a site may not serve. One bad year
    should cost that year, not the council."""
    scraper = _InfoCouncil()
    scraper.fetcher = _Fetcher(
        {f"{LISTING_URL}?year=2026": GRID}, requests.Timeout("read timed out")
    )

    result = _adapter_result(scraper, [2025, 2026])

    assert result["ok"] is True
    assert [m["date"] for m in result["meetings"]] == ["2026-03-12"]


def test_infocouncil_warns_about_a_failed_year(caplog):
    scraper = _InfoCouncil()
    scraper.fetcher = _Fetcher(
        {f"{LISTING_URL}?year=2026": GRID}, requests.Timeout("read timed out")
    )
    scraper.years_filter = [2025, 2026]

    scraper.scraper()

    assert any(
        r.levelname == "WARNING" and "2025" in r.getMessage() for r in caplog.records
    )


def test_docspublished_fails_the_council_when_the_api_times_out():
    """api.docassembler.com.au is the host that once stalled a run for 12+
    minutes. Its timeout has to come back as a failure, not as 0 meetings."""
    scraper = _DocsPublished()
    scraper.fetcher = _Fetcher({}, requests.Timeout("read timed out"))

    result = _adapter_result(scraper, [2026])

    assert result["ok"] is False
    assert "timed out" in result["error"]["message"]


def test_docspublished_fails_the_council_when_the_api_returns_nothing():
    scraper = _DocsPublished()
    scraper.fetcher = _Fetcher(
        {f"{DocsPublishedScraper.API_ROOT}/organisation/example": ""},
        requests.ConnectionError("unreachable"),
    )

    result = _adapter_result(scraper, [2026])

    assert result["ok"] is False


class _Driver:
    """Stands in for a webdriver: only `service.process` is read."""

    def __init__(self, process):
        self.service = type("Service", (), {"process": process})()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_abandon_kills_the_browser_and_its_driver():
    """chromedriver dying does not take Chrome with it, so abandon() has to
    signal both. A shell stands in for chromedriver and its backgrounded
    sleep for Chrome."""
    driver = subprocess.Popen(["sh", "-c", "sleep 60 & wait"])
    try:
        deadline = time.monotonic() + 5
        browser = []
        while not browser and time.monotonic() < deadline:
            browser = subprocess.run(
                ["pgrep", "-P", str(driver.pid)], capture_output=True, text=True
            ).stdout.split()
        assert browser, "the stand-in browser never started"

        fetcher = DefaultFetcher()
        fetcher._DefaultFetcher__driver = _Driver(driver)
        fetcher.abandon()

        driver.wait(timeout=5)
        deadline = time.monotonic() + 5
        while _alive(int(browser[0])) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(int(browser[0]))
    finally:
        if driver.poll() is None:
            driver.kill()


def test_abandon_without_a_browser_does_nothing():
    DefaultFetcher().abandon()


class _ClosingFetcher(_Fetcher):
    closed = 0

    def close(self):
        self.closed += 1


@pytest.mark.parametrize(
    "pages",
    [{f"{LISTING_URL}?year=2026": GRID}, {}],
    ids=["finished", "failed"],
)
def test_run_scraper_closes_the_browser_however_the_scraper_ends(pages):
    """Nothing else closes a scraper's Chrome, so without this every browser
    any council opened stays alive until the whole run exits."""
    scraper = _InfoCouncil()
    scraper.fetcher = _ClosingFetcher(pages, requests.Timeout("read timed out"))

    _adapter_result(scraper, [2026])

    assert scraper.fetcher.closed == 1


class _QuitFails:
    def __init__(self, process):
        self.service = type("Service", (), {"process": process})()

    def quit(self):
        raise RuntimeError("session already gone")


def test_close_kills_a_browser_it_cannot_quit_and_forgets_it():
    driver = subprocess.Popen(["sh", "-c", "sleep 60"])
    try:
        fetcher = DefaultFetcher()
        fetcher._DefaultFetcher__driver = _QuitFails(driver)

        fetcher.close()

        driver.wait(timeout=5)
        assert fetcher._DefaultFetcher__driver is None
    finally:
        if driver.poll() is None:
            driver.kill()
