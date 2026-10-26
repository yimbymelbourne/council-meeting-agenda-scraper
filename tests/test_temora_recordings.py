"""Temora's month-only minutes take their day from the meeting's recording.

Each month section of a Minutes-from-<year> page links its minutes and its
YouTube recording, and the recording's oEmbed title gives the full date
("9th June 2026 Extraordinary Council Meeting"). A minutes is paired with
the recording in its own section whose title names the same meeting type
and a date in the section's month; anything else falls back to `misfiled`,
then is left out. Run against a page built here, so each case is one month.
"""

from __future__ import annotations

import datetime
import json
from urllib.parse import parse_qs, urlparse

import requests

from aus_council_scrapers import clock
from aus_council_scrapers.scrapers.nsw.temora import TemoraScraper

_MEETINGS = "https://www.temora.nsw.gov.au/Your-Council/Council-Meetings"
_INDEX = f"{_MEETINGS}/Past-Council-Minutes"
_YEAR = f"{_INDEX}/Minutes-from-2026"
_FILES = "/files/assets/public/v/1/council-meetings/2026-meeting-documents/minutes"

_TITLES = {
    "ordJune2026": "18th June 2026 Ordinary Council Meeting",
    "extJune2026": "9th June 2026 Extraordinary Council Meeting",
    # September's section links August's recording.
    "ordAug20260": "20th August 2026 Ordinary Council Meeting",
    "deletedVid0": None,  # oEmbed answers 404
}


def _section(month: str, links: list[tuple[str, str]]) -> str:
    anchors = "".join(f'<p><a href="{href}">{text}</a></p>' for text, href in links)
    return f"<h2>{month} 2026</h2>{anchors}"


_PAGE = (
    '<div id="main-content">'
    + _section(
        "June",
        [
            (
                "Read the June 2026 Extraordinary Meeting Minutes",
                f"{_FILES}/june-2026-extraordinary-council-minutes.pdf",
            ),
            (
                "View the June 2026 Extraordinary Meeting Livestream",
                "https://youtu.be/extJune2026",
            ),
            (
                "Listen to the June 2026 Ordinary Meeting Recording",
                "https://youtu.be/ordJune2026",
            ),
            (
                "Read the June 2026 Ordinary Meeting Minutes",
                f"{_FILES}/june-2026-action-minutes.pdf",
            ),
        ],
    )
    # No recording at all: dated by `misfiled` when it has an entry.
    + _section(
        "July", [("Read the July minutes", f"{_FILES}/july-2026-action-minutes.pdf")]
    )
    + _section(
        "September",
        [
            (
                "Watch the September meeting",
                "https://www.youtube.com/watch?v=ordAug20260",
            ),
            (
                "Read the September minutes",
                f"{_FILES}/september-2026-action-minutes.pdf",
            ),
        ],
    )
    # A recording that is gone, and no `misfiled` entry: left out.
    + _section(
        "October",
        [
            ("Watch the October meeting", "https://youtu.be/deletedVid0"),
            ("Read the October minutes", f"{_FILES}/october-2026-action-minutes.pdf"),
        ],
    )
    + "</div>"
)


class _Fetcher:
    def __init__(self):
        self.oembed: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url == _INDEX:
            return f'<div id="main-content"><a href="{_YEAR}">2026</a></div>'
        if url == f"{_MEETINGS}/Business-Papers":
            return '<div id="main-content"></div>'
        if url == _YEAR:
            return _PAGE
        if url.startswith("https://www.youtube.com/oembed?"):
            watch = parse_qs(urlparse(url).query)["url"][0]
            video = parse_qs(urlparse(watch).query)["v"][0]
            self.oembed.append(video)
            title = _TITLES[video]
            if title is None:
                raise requests.HTTPError(f"404 Client Error: Not Found for url: {url}")
            return json.dumps({"title": title, "author_name": "Temora Shire Council"})
        raise AssertionError(f"unexpected request {url}")


def _run(misfiled: dict) -> tuple[dict[str, str], _Fetcher]:
    scraper = TemoraScraper()
    scraper.misfiled = misfiled
    fetcher = _Fetcher()
    scraper.fetcher = fetcher
    scraper.years_filter = [2026]
    with clock.frozen("2026-10-26"):
        results = scraper.scraper()
    return {r.minutes_url.rsplit("/", 1)[-1]: r.date for r in results}, fetcher


def test_month_only_minutes_take_the_day_of_their_own_recording():
    dates, fetcher = _run({"july-2026-action-minutes.pdf": datetime.date(2026, 7, 16)})

    assert dates == {
        # One month, two meetings: each minutes takes the recording of its
        # own meeting type.
        "june-2026-extraordinary-council-minutes.pdf": "2026-06-09",
        "june-2026-action-minutes.pdf": "2026-06-18",
        # No recording, so `misfiled` dates it.
        "july-2026-action-minutes.pdf": "2026-07-16",
        # September's recording is titled 20 August: not September's day,
        # and no `misfiled` entry, so left out. So is October, whose
        # recording is gone.
    }
    # Only recordings beside a month-only minutes are asked for, once each.
    assert sorted(fetcher.oembed) == sorted(
        ["extJune2026", "ordJune2026", "ordAug20260", "deletedVid0"]
    )


def test_without_misfiled_a_month_with_no_recording_is_left_out():
    dates, _ = _run({})

    assert "july-2026-action-minutes.pdf" not in dates
    assert dates["june-2026-action-minutes.pdf"] == "2026-06-18"
