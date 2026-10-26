"""CouncilConnectDocumentLibraryScraper: what one production night costs, and
the rule that a meeting's day is never made up.

The replay test in scraper_test.py pins each council's full history, but it
is recorded unfiltered, so it says nothing about what a one-year production
run fetches; and a re-record would carry a change of dating policy (say,
emitting the 1st of the month for a month-only label) straight into the
fixtures. These cover both.
"""

from __future__ import annotations

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from aus_council_scrapers.councilconnect_library import (
    CouncilConnectDocumentLibraryScraper,
)
from tests.cassette import PlaybackFetcher, cassette_paths

LIBRARY_SCRAPERS = {
    "KojonupScraper": "kojonup",
    "BoyupBrookScraper": "boyup_brook",
    "NorthamptonScraper": "northampton",
    "NarroginScraper": "narrogin",
    "YilgarnScraper": "yilgarn",
    "MurchisonScraper": "murchison",
    "YalgooScraper": "yalgoo",
    "CuballingScraper": "cuballing",
    "MorawaScraper": "morawa",
}

# The index, the year's agenda and minutes folders, an undated folder and a
# meeting-dates page at most; well inside the ~20 AGENTS.md asks for.
REQUEST_BUDGET = 5


class _CountingPlayback(PlaybackFetcher):
    def __init__(self, replay_data, slug):
        super().__init__(replay_data, slug)
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.requested.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _key(r: dict) -> tuple:
    return (r["date"], r["name"], r["agenda_url"] or "", r["minutes_url"] or "")


@pytest.mark.parametrize("class_name", sorted(LIBRARY_SCRAPERS))
def test_one_production_year_reads_only_that_years_folders(class_name):
    slug = LIBRARY_SCRAPERS[class_name]
    result_path, replay_path = cassette_paths(slug)
    with open(replay_path) as f:
        replay = json.load(f)
    with open(result_path) as f:
        expected = json.load(f)

    # A fresh instance: the registry's is shared with the replay tests.
    scraper = type(SCRAPER_REGISTRY[class_name])()
    fetcher = _CountingPlayback(replay, slug)
    scraper.fetcher = fetcher
    year = int(fetcher.recorded_date[:4])
    scraper.years_filter = [year]
    with clock.frozen(fetcher.recorded_date):
        results = [r.to_dict() for r in scraper.scraper()]

    assert sorted(map(_key, results)) == sorted(
        _key(r) for r in expected if r["date"].startswith(str(year))
    )
    assert len(fetcher.requested) <= REQUEST_BUDGET, fetcher.requested


# --------------------------------------------------------------------------
# Month-only labels, on a library built here
# --------------------------------------------------------------------------

_BASE = "https://library.example"


def _index(*folders: tuple[int, str]) -> str:
    options = "".join(f'<option value="{i}">{label}</option>' for i, label in folders)
    return (
        '<select class="categories-dropdown"><option value="0">Any Category</option>'
        f"{options}</select>"
    )


def _folder(*items: tuple[int, str, str]) -> str:
    rows = "".join(
        f'<tr><td class="table-title"><a class="doc-pdf" href="/documents/{i}/x">'
        f'{label} <span class="table-date">({stamp})</span></a></td></tr>'
        for i, label, stamp in items
    )
    return f'<div class="documentcentre-items"><table>{rows}</table></div>'


class _FakeFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch_with_requests(self, url, method="GET", **kwargs):
        return self.pages[url]

    def sleep(self, seconds):
        pass


def _scrape(
    folders: dict[str, list],
    schedule: str | None = None,
    corrections: dict | None = None,
    today: str = "2026-10-20",
):
    class Library(CouncilConnectDocumentLibraryScraper):
        schedule_path = "/dates.aspx" if schedule is not None else None

        def __init__(self):
            super().__init__("example", "WA", _BASE)

    Library.corrections = {
        f"{_BASE}/documents/{i}/x": c for i, c in (corrections or {}).items()
    }

    labels = list(folders)
    pages = {f"{_BASE}/documents/": _index(*enumerate(labels, start=1))}
    for i, label in enumerate(labels, start=1):
        pages[f"{_BASE}/documents/?CategoryId={i}"] = _folder(*folders[label])
    if schedule is not None:
        pages[f"{_BASE}/dates.aspx"] = f"<main>{schedule}</main>"
    scraper = Library()
    scraper.fetcher = _FakeFetcher(pages)
    scraper.years_filter = [int(today[:4])]
    with clock.frozen(today):
        return {(r.date, r.name, r.time): r for r in scraper.scraper()}


def test_a_month_only_paper_takes_its_day_from_a_dated_paper_of_the_same_meeting():
    meetings = _scrape(
        {
            "Agendas 2026": [
                (1, "September 2026 Ordinary Council Meeting agenda", "21/09/2026")
            ],
            "Minutes 2026": [
                (
                    2,
                    "Minutes - Ordinary Council Meeting 23 September 2026",
                    "02/10/2026",
                )
            ],
        }
    )
    meeting = meetings[("2026-09-23", "Ordinary Council Meeting", None)]
    assert meeting.agenda_url == f"{_BASE}/documents/1/x"
    assert meeting.minutes_url == f"{_BASE}/documents/2/x"


def test_a_month_only_paper_with_no_published_day_is_left_out():
    # The upload stamp is a date, and the only one there is; it must not
    # become the meeting's. A dated special meeting keeps the run non-empty.
    meetings = _scrape(
        {
            "Agendas 2026": [
                (1, "Agenda OCM September 2026", "21/09/2026"),
                (2, "Special Council Meeting Agenda 2 June 2026", "28/05/2026"),
            ],
        }
    )
    assert list(meetings) == [("2026-06-02", "Special Council Meeting", None)]


def test_the_schedule_dates_ordinary_meetings_only():
    meetings = _scrape(
        {
            "Agendas 2026": [
                (1, "09.2026 - Agenda - September 2026 Council Meeting", "11/09/2026"),
                (
                    2,
                    "09.2026 - Agenda - September 2026 Special Council Meeting",
                    "01/09/2026",
                ),
            ],
        },
        schedule="<p>Thursday, 17th September 2026 Council Chambers</p>",
    )
    assert list(meetings) == [("2026-09-17", "Ordinary Council Meeting", None)]


def test_a_library_with_no_papers_for_the_year_fails_the_council():
    with pytest.raises(RuntimeError, match="no meetings with papers"):
        _scrape({"Agendas 2026": [(1, "Agenda OCM September 2026", "21/09/2026")]})


def test_the_schedule_ignores_an_electors_meeting_in_the_same_month():
    # Cuballing lists its electors' meeting above the ordinary meetings;
    # counted, February would have two dates and so none.
    meetings = _scrape(
        {"Agendas 2026": [(1, "February 2026 Ordinary Council Meeting agenda", "")]},
        schedule=(
            "<ul><li>Annual General Meeting of Electors - 4.30pm Wednesday 4 "
            "February 2026</li><li>18 February 2026</li></ul>"
        ),
    )
    assert list(meetings) == [("2026-02-18", "Ordinary Council Meeting", None)]


def test_dated_minutes_win_over_the_schedule():
    # Cuballing's page gave 15 April 2026; the minutes say the 23rd.
    meetings = _scrape(
        {
            "Agendas 2026": [(1, "April 2026 Ordinary Council Meeting agenda", "")],
            "Minutes 2026": [
                (2, "Minutes - Ordinary Council Meeting 23 April 2026", "")
            ],
        },
        schedule="<p>15 April 2026</p>",
    )
    assert list(meetings) == [("2026-04-23", "Ordinary Council Meeting", None)]


def test_two_meetings_of_one_type_on_one_day_are_kept_apart_by_time():
    # Boyup Brook, 2 March 2023: a special meeting to appoint a CEO and
    # another to award a tender, each with its own agenda and minutes.
    meetings = _scrape(
        {
            "Agendas 2023": [
                (1, "Special Council Agenda - 2 March 2023 - Appoint CEO", ""),
                (2, "Special Council Agenda - 2 March 2023 - Tender 23/001", ""),
            ],
            "Minutes 2023": [
                (3, "Special Council Minutes (Appointment of CEO) - 2 March 2023", ""),
                (4, "Special Council Minutes (Tender 23/001) - 2 March 2023", ""),
            ],
        },
        corrections={
            1: {"time": "3:00 PM"},
            3: {"time": "3:00 PM"},
            2: {"time": "3:30 PM"},
            4: {"time": "3:30 PM"},
        },
        today="2023-10-20",
    )
    ceo = meetings[("2023-03-02", "Special Council Meeting", "3:00 PM")]
    tender = meetings[("2023-03-02", "Special Council Meeting", "3:30 PM")]
    assert (ceo.agenda_url, ceo.minutes_url) == (
        f"{_BASE}/documents/1/x",
        f"{_BASE}/documents/3/x",
    )
    assert (tender.agenda_url, tender.minutes_url) == (
        f"{_BASE}/documents/2/x",
        f"{_BASE}/documents/4/x",
    )


def test_the_new_year_before_its_first_paper_is_not_a_failure():
    # Production asks for the current year only, and its folders do not
    # exist until a paper is filed.
    last_year = {"Agendas 2025": [(1, "Agenda OCM 18 December 2025", "")]}
    assert _scrape(last_year, today="2026-01-20") == {}


def test_a_missing_folder_after_march_still_fails_the_council():
    last_year = {"Agendas 2025": [(1, "Agenda OCM 18 December 2025", "")]}
    with pytest.raises(RuntimeError, match="no meetings with papers"):
        _scrape(last_year, today="2026-04-20")


def test_an_empty_folder_for_the_new_year_still_fails_the_council():
    folders = {
        "Agendas 2025": [(1, "Agenda OCM 18 December 2025", "")],
        "Agendas 2026": [(2, "Agenda OCM February 2026", "")],
    }
    with pytest.raises(RuntimeError, match="no meetings with papers"):
        _scrape(folders, today="2026-02-10")
