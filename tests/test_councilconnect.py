"""The production fetch bound for CouncilConnect councils.

Cassettes are recorded unfiltered, so the replay test in scraper_test.py
proves the full history parses but says nothing about what one production
night costs. Production passes a single year, and on these sites most
meetings cost a request of their own, so a scraper that stopped honouring
`years_filter` would still pass replay while fetching seven years a night out
of the shared 600 s budget. This replays the same cassettes with the filter
production uses and checks both halves of the bargain: it fetches only that
year, and it still finds every meeting of that year.

The budget check covers only the recording year. Cottesloe pays a request per
meeting, and that year had 13; a 20-meeting year such as 2023 costs ~24, so
this test would not have caught that.

The councils restricted to their Council meetings (`meeting_types`) are held
to the same bound, so a change that started reading every type—or the
per-type listings of every year—would fail here rather than in production.
Nedlands is allowed more: it held 20 Council meetings by October 2026, and
each costs a request whatever the scraper does.

Below those: what a failed meeting page does to the run, and the document
and date choices the cassettes pin down only in passing.
"""

import datetime
import json
import re

import pytest
import requests
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

# One production year should stay within ~20 requests (see AGENTS.md on the
# 600 s budget).
REQUEST_BUDGET = 20
# Councils whose Council meetings alone exceed that; see the module docstring.
REQUEST_BUDGET_OVERRIDES = {"NedlandsScraper": 26}

COUNCILCONNECT_SCRAPERS = [
    "CottesloeScraper",
    "EastFremantleScraper",
    "PeppermintGroveScraper",
    "MurrayWAScraper",
    "BassendeanScraper",
    "VictoriaParkScraper",
    "NedlandsScraper",
]

# The file store's own address for a meeting document: the <ver> segment goes
# up whenever the council edits the meeting, so a URL with it changes from
# night to night and council-alerts, which keys meetings on agenda_url, would
# record the meeting again each time.
VERSIONED_DOCUMENT = re.compile(r"/moduledata/councilmeetings/[^/]+/\d+\.\d+/")


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize("class_name", COUNCILCONNECT_SCRAPERS)
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        fetcher = _Counting(json.load(f), scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)

    year = int(fetcher.recorded_date[:4])
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    try:
        with clock.frozen(fetcher.recorded_date):
            result = scraper.scraper()
    finally:
        del scraper.years_filter

    other_years = [
        u for u in fetcher.urls if "/past/" in u and f"/past/{year}" not in u
    ]
    assert other_years == []
    assert len(fetcher.urls) <= REQUEST_BUDGET_OVERRIDES.get(class_name, REQUEST_BUDGET)
    assert [r.to_dict() for r in result] == [
        m for m in recorded if m["date"].startswith(str(year))
    ]


@pytest.mark.parametrize("class_name", COUNCILCONNECT_SCRAPERS)
def test_document_urls_carry_no_file_store_version(class_name):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, _ = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)

    versioned = [
        m[field]
        for m in recorded
        for field in ("agenda_url", "minutes_url", "download_url")
        if m[field] and VERSIONED_DOCUMENT.search(m[field])
    ]
    assert versioned == []


def _not_found(url: str, live: bool) -> requests.HTTPError:
    """A 404 as the live fetcher raises it, or as a cassette replays it."""
    message = f"404 Client Error: Not Found for url: {url}"
    if not live:
        return requests.HTTPError(message)
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError(message, response=response)


class _NoListings(PlaybackFetcher):
    """Replays a cassette as though no year listing existed yet."""

    live = False

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if "/past/" in url:
            raise _not_found(url, self.live)
        return super().fetch_with_requests(url, method, **kwargs)


def _scrape_without_listings(year_offset: int, live: bool):
    scraper = SCRAPER_REGISTRY["MurrayWAScraper"]
    _, replay_path = cassette_paths(scraper.council_name)
    with open(replay_path) as f:
        fetcher = _NoListings(json.load(f), scraper.council_name)
    fetcher.live = live
    year = int(fetcher.recorded_date[:4])
    scraper.fetcher = fetcher
    scraper.years_filter = [year + year_offset]
    try:
        with clock.frozen(fetcher.recorded_date):
            return scraper.scraper()
    finally:
        del scraper.years_filter


@pytest.mark.parametrize("live", [True, False])
def test_missing_listing_for_the_new_year_leaves_the_upcoming_meetings(live):
    # Every January, until the year's first meeting is entered, the current
    # year has no listing and 404s. That must not cost the meetings whose
    # agendas are already out on the upcoming page.
    scraper = SCRAPER_REGISTRY["MurrayWAScraper"]
    result_path, _ = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)

    result = _scrape_without_listings(0, live)

    upcoming = [r.to_dict() for r in result]
    assert upcoming
    assert all(m in recorded for m in upcoming)


@pytest.mark.parametrize("live", [True, False])
def test_missing_listing_for_an_earlier_year_still_fails(live):
    # An earlier year 404ing means the module moved or the site changed, and
    # carrying on would report that year as having no meetings.
    with pytest.raises(requests.HTTPError):
        _scrape_without_listings(-1, live)


def _pager(*parts: str) -> BeautifulSoup:
    """A dpMeetings pager as the sites write it: links, and the current page
    as a plain span. No cassette pages past five—the per-type listings the
    restricted councils read are at most two pages—so this markup is copied
    from Victoria Park's 2025 all-types listing (62 meetings, 7 pages)."""
    html = "".join(
        (
            f"<span>{p[1:-1]}</span>"
            if p.startswith("[")
            else f"<a href=\"javascript:__doPostBack('pager${p}','')\">{p}</a>"
        )
        for p in parts
    )
    return BeautifulSoup(
        f'<span id="x_lvMeetings_dpMeetings">{html}</span>', "html.parser"
    )


@pytest.mark.parametrize(
    "parts, page, target",
    [
        (["[1]", "2", "3", "4", "5", "..."], 1, "pager$2"),
        # Past the fifth page the next block is behind the trailing "...".
        (["1", "2", "3", "4", "[5]", "..."], 5, "pager$..."),
        (["...", "[6]", "7"], 6, "pager$7"),
        (["...", "6", "[7]"], 7, None),
        # The last page of a block of one: its only link goes back, and
        # following it would page forever.
        (["...", "[6]"], 6, None),
    ],
)
def test_pager_follows_the_next_block_and_never_goes_back(parts, page, target):
    scraper = SCRAPER_REGISTRY["VictoriaParkScraper"]
    assert scraper._next_page_target(_pager(*parts), page) == target


class _FailsOneMeeting(PlaybackFetcher):
    """Replays a cassette with one meeting page failing as `error` says."""

    error: Exception

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url == self.failing_url:
            raise self.error
        return super().fetch_with_requests(url, method, **kwargs)


def _scrape_with_one_meeting_failing(make_error):
    scraper = SCRAPER_REGISTRY["MurrayWAScraper"]
    result_path, replay_path = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)
    with open(replay_path) as f:
        fetcher = _FailsOneMeeting(json.load(f), scraper.council_name)
    year = int(fetcher.recorded_date[:4])
    this_year = [m for m in recorded if m["date"].startswith(str(year))]
    fetcher.failing_url = this_year[-1]["webpage_url"]
    fetcher.error = make_error(fetcher.failing_url)
    scraper.fetcher = fetcher
    scraper.years_filter = [year]
    try:
        with clock.frozen(fetcher.recorded_date):
            return this_year, fetcher.failing_url, scraper.scraper()
    finally:
        del scraper.years_filter


def test_failed_meeting_page_fails_the_council():
    # A 5xx or timeout after the fetcher's retries means the site is in
    # trouble; reporting success with that meeting missing would hide it.
    def server_error(url):
        response = requests.Response()
        response.status_code = 503
        return requests.HTTPError(f"503 for {url}", response=response)

    with pytest.raises(requests.HTTPError):
        _scrape_with_one_meeting_failing(server_error)
    with pytest.raises(requests.ConnectionError):
        _scrape_with_one_meeting_failing(lambda url: requests.ConnectionError(url))


@pytest.mark.parametrize("live", [True, False])
def test_deleted_meeting_page_costs_only_that_meeting(live):
    this_year, gone, result = _scrape_with_one_meeting_failing(
        lambda url: _not_found(url, live)
    )
    assert [r.to_dict() for r in result] == [
        m for m in this_year if m["webpage_url"] != gone
    ]


_PAGE = "https://x/council-meetings/ordinary-council-meeting/m/1"


@pytest.mark.parametrize(
    "links, agenda, minutes",
    [
        # Nedlands, 25 February 2025: minutes that say they leave the
        # attachments out are the minutes, not an attachment.
        (
            [
                ("Agenda", "Council Meeting Agenda 25 February 2025", "a.pdf"),
                (
                    "Minutes",
                    "Council Meeting - MINUTES -25 February 2025 PUBLIC "
                    "(Excluding Attachments)",
                    "m.pdf",
                ),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Victoria Park, 13 December 2022: the amended agenda is the full
        # agenda with a cover memo, and the one the meeting worked from.
        (
            [
                ("Documents", "Agenda", "agenda.pdf"),
                ("Documents", "Agenda Amended", "agenda-amended.pdf"),
                ("Documents", "Minutes", "minutes.pdf"),
            ],
            "agenda-amended.pdf",
            "minutes.pdf",
        ),
    ],
)
def test_pick_documents(links, agenda, minutes):
    scraper = SCRAPER_REGISTRY["NedlandsScraper"]
    picked = scraper._pick_documents(
        [(group, label, f"{_PAGE}/documents/{name}") for group, label, name in links]
    )
    assert picked == (f"{_PAGE}/documents/{agenda}", f"{_PAGE}/documents/{minutes}")


@pytest.mark.parametrize(
    "heading, field, files, expected",
    [
        # Peppermint Grove: the date field says the 14th; the heading, the
        # agenda and the minutes all say the 21st.
        (
            "Ordinary Council Meeting 21 December 2021",
            "2021-12-14",
            [
                "final-ordinary-council-meeting-agenda-21-december-2021.pdf",
                "ocm-21-december-minutes.pdf",
            ],
            "2021-12-21",
        ),
        # Nedlands: the heading has last year's date; the documents back the
        # field.
        (
            "Ordinary Council Meeting - 28 January 2025",
            "2026-01-28",
            [
                "ordinary-council-meeting-28-january-2026-agenda.pdf",
                "public-minutes-ordinary-council-meeting-28-january-2026.pdf",
            ],
            "2026-01-28",
        ),
        # Nothing in the filenames to settle it: the field stands.
        (
            "Ordinary Council Meeting - 22 April 2025 - Reconvened 06 May 2025",
            "2025-05-06",
            ["public-agenda-ordinary-council-meeting-april-2025-(1).pdf"],
            "2025-05-06",
        ),
    ],
)
def test_heading_date_wins_only_with_the_documents_behind_it(
    heading, field, files, expected
):
    scraper = SCRAPER_REGISTRY["PeppermintGroveScraper"]
    got = scraper._heading_date_if_documents_agree(
        heading,
        datetime.date.fromisoformat(field),
        [f"{_PAGE}/documents/{name}" for name in files],
    )
    assert got.isoformat() == expected
