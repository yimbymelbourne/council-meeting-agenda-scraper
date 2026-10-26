"""Fetch behaviour of the C-4 scrapers that cassette replay cannot see.

Replay only ever exercises the path a cassette was recorded on, and every
cassette here was recorded from a home IP where every fetch succeeded. Two
production paths are therefore untested by it:

- A failed fetch in a one-year production run. If a scraper caught it and
  returned [], main.py would count the council as working with 0 meetings.
- Mount Gambier's AWS WAF challenge (202 with an empty body), which a
  GitHub runner may get where home did not. The scraper must switch to
  Selenium and still read the archive, not report an empty one.
"""

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.richmond_valley import RichmondValleyScraper
from aus_council_scrapers.scrapers.qld.mareeba import MareebaScraper
from aus_council_scrapers.scrapers.qld.tablelands import TablelandsScraper
from aus_council_scrapers.scrapers.sa.mount_gambier import MountGambierScraper
from aus_council_scrapers.scrapers.vic.golden_plains import GoldenPlainsScraper
from aus_council_scrapers.scrapers.wa.karratha import KarrathaScraper
from tests.cassette import cassette_paths


class _Unreachable(Exception):
    pass


def _refuse(*args, **kwargs):
    raise _Unreachable("connection refused")


@pytest.mark.parametrize(
    "scraper_class",
    [
        RichmondValleyScraper,
        MareebaScraper,
        TablelandsScraper,
        MountGambierScraper,
        GoldenPlainsScraper,
        KarrathaScraper,
    ],
)
def test_one_year_with_every_fetch_failing_raises(scraper_class, monkeypatch):
    scraper = scraper_class()
    scraper.years_filter = [2026]
    monkeypatch.setattr(scraper.fetcher, "fetch_with_requests", _refuse)
    monkeypatch.setattr(scraper.fetcher, "fetch_with_selenium", _refuse)
    with pytest.raises(_Unreachable):
        scraper.scraper()


class _ChallengedFetcher:
    """Answers every requests fetch with the WAF's empty body, and serves the
    recorded archive pages only through Selenium."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.selenium_urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return ""

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        self.selenium_urls.append(url)
        return self.pages[url]


def test_mount_gambier_reads_through_selenium_when_requests_is_challenged():
    _, replay_path = cassette_paths("mount_gambier")
    with open(replay_path) as f:
        replay = json.load(f)
    pages = {key[1]: value for key, value in replay if key[0] == "requests"}
    recorded_date = next(
        value for key, value in replay if key == ["meta", "recorded_date"]
    )

    def run(fetcher):
        scraper = MountGambierScraper()
        scraper.years_filter = [2025]
        scraper.fetcher = fetcher
        with clock.frozen(recorded_date):
            return scraper.scraper()

    challenged = _ChallengedFetcher(pages)
    through_selenium = run(challenged)

    class _Direct(_ChallengedFetcher):
        def fetch_with_requests(self, url, method="GET", **kwargs):
            return self.pages[url]

    direct = run(_Direct(pages))

    assert challenged.selenium_urls, "never fell back to Selenium"
    assert through_selenium and through_selenium == direct


def _recorded(slug: str) -> tuple[dict[str, str], str]:
    _, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    pages = {key[1]: value for key, value in replay if key[0] == "requests"}
    recorded_date = next(
        value for key, value in replay if key == ["meta", "recorded_date"]
    )
    return pages, recorded_date


class _PageFetcher:
    """Serves recorded pages, with any of them swapped for `overrides`."""

    def __init__(self, pages: dict[str, str], overrides: dict[str, str]):
        self.pages = {**pages, **overrides}

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.pages[url]


_GUTTED = "<html><body><p>Page under maintenance</p></body></html>"


def test_richmond_valley_raises_when_a_linked_year_page_lists_nothing():
    # The index still links the 2026 page, so this is not the "year page
    # missing" case: the page's table markup is what has gone.
    pages, recorded_date = _recorded("richmond_valley")
    year_page = next(url for url in pages if "2026-agendas-and-minutes" in url)
    scraper = RichmondValleyScraper()
    scraper.years_filter = [2026]
    scraper.fetcher = _PageFetcher(pages, {year_page: _GUTTED})
    with clock.frozen(recorded_date), pytest.raises(RuntimeError):
        scraper.scraper()


def test_golden_plains_raises_when_the_minutes_page_yields_nothing():
    # Agendas still read; without the guard every meeting would come out
    # agenda-only and the run would look healthy.
    pages, recorded_date = _recorded("golden_plains")
    minutes_page = next(url for url in pages if url.endswith("meeting-minutes"))
    scraper = GoldenPlainsScraper()
    scraper.years_filter = [2026]
    scraper.fetcher = _PageFetcher(pages, {minutes_page: _GUTTED})
    with clock.frozen(recorded_date), pytest.raises(RuntimeError):
        scraper.scraper()


def _mount_gambier_page(rows: list[tuple[str, str, str, str]]) -> str:
    """An archive page holding `rows` of (title, committee, type, file)."""
    body = "".join(
        f"<tr><td><a href='https://cdn.mountgambier.sa.gov.au/agendas-minutes/"
        f"{file}'>{title}</a></td><td>{committee}</td><td>{kind}</td>"
        f"<td>18 June 2024</td></tr>"
        for title, committee, kind, file in rows
    )
    return (
        "<html><body><select name='year'><option value='2024'>2024</option>"
        f"</select><div class='archive'><table><tbody>{body}</tbody></table>"
        "</div></body></html>"
    )


def _mount_gambier_meeting(rows) -> dict:
    page = _mount_gambier_page(rows)

    class _Fetcher:
        def fetch_with_requests(self, url, method="GET", **kwargs):
            return page

    scraper = MountGambierScraper()
    scraper.years_filter = [2024]
    scraper.fetcher = _Fetcher()
    with clock.frozen("2026-10-20"):
        (meeting,) = scraper.scraper()
    return meeting


def test_mount_gambier_never_takes_a_supplementary_paper_as_the_agenda():
    # The live 2024 archive lists the supplementary item first.
    meeting = _mount_gambier_meeting(
        [
            (
                "Supplementary Agenda Item",
                "Council",
                "Agenda",
                "Supplementary-Agenda-Item-Council-Meeting-18-June-2024.pdf",
            ),
            (
                "Council - Agenda",
                "Council",
                "Agenda",
                "Agenda-Council-18-June-2024.pdf",
            ),
        ]
    )
    assert meeting.agenda_url.endswith("/Agenda-Council-18-June-2024.pdf")


def test_mount_gambier_takes_open_confirmed_minutes():
    meeting = _mount_gambier_meeting(
        [
            ("Council - Agenda", "Council", "Agenda", "Agenda-No-In-Confidence.pdf"),
            (
                "Council - In-Confidence Minutes",
                "Council",
                "Minutes",
                "Confidential-Council-Minutes.pdf",
            ),
            ("Council - Minutes", "Council", "Minutes", "Council-Minutes.pdf"),
            ("Council - Minutes", "Council", "Minutes", "Confirmed-Minutes.pdf"),
        ]
    )
    # "No-In-Confidence" is the open copy, not a confidential one.
    assert meeting.agenda_url.endswith("/Agenda-No-In-Confidence.pdf")
    assert meeting.minutes_url.endswith("/Confirmed-Minutes.pdf")
