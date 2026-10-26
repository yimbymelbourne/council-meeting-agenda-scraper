"""The nine small-shire CouncilConnect scrapers (`councilconnect_small_shires.py`).

Replay in scraper_test.py proves each full history still parses the same
way. Two things it cannot see are pinned here:

- **What one production night costs.** Cassettes are recorded unfiltered,
  so a scraper that stopped honouring `years_filter`, or stopped skipping
  committees before fetching their pages, would still replay. The same check
  as test_councilconnect.py's, against these councils' cassettes.
- **The label and heading habits the shared class absorbs**, as tables of
  what each shire actually typed, so a change to the base's rules that
  starts dropping one of these agendas or names fails here by name.
"""

import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

SHIRES = [
    "PerenjoriScraper",
    "MukinbudinScraper",
    "MenziesScraper",
    "WanderingScraper",
    "WyalkatchemScraper",
    "TamminScraper",
    "TrayningScraper",
    "CueScraper",
    "UpperGascoyneScraper",
]

REQUEST_BUDGET = 20

_PAGE = "https://www.example.wa.gov.au/council-meetings/ordinary-council-meeting/x/1"


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize("class_name", SHIRES)
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
    assert len(fetcher.urls) <= REQUEST_BUDGET
    assert [r.to_dict() for r in result] == [
        m for m in recorded if m["date"].startswith(str(year))
    ]


@pytest.mark.parametrize(
    "class_name, links, agenda, minutes",
    [
        # Perenjori: the only agenda is the packet, written with "&".
        (
            "PerenjoriScraper",
            [
                (
                    "Agenda",
                    "Ordinary Council Meeting Agenda & Attachments - 24 September 2026",
                    "ordinary-council-meeting-agenda-and-attachments-24-september-2026.pdf",
                ),
                (
                    "Unconfirmed_Minutes",
                    "Unconfirmed Ordinary Council Meeting Minutes - 24 September 2026",
                    "2-ordinary-council-meeting-minutes-(web)-24-september-2026.pdf",
                ),
            ],
            "ordinary-council-meeting-agenda-and-attachments-24-september-2026.pdf",
            "2-ordinary-council-meeting-minutes-(web)-24-september-2026.pdf",
        ),
        # Tammin 2020: a label led by a dotted date is not an item number.
        (
            "TamminScraper",
            [
                (
                    "Agenda",
                    "22.12.2020 Special Council Meeting Agenda",
                    "22122020-special-council-meeting-agenda.pdf",
                ),
                (
                    "Minutes",
                    "22.12.2020 Special Council Meeting Minutes",
                    "22122020-special-council-meeting-minutes.pdf",
                ),
            ],
            "22122020-special-council-meeting-agenda.pdf",
            "22122020-special-council-meeting-minutes.pdf",
        ),
        # Tammin, March 2021: the dotted date runs straight into the name,
        # with no space for a word boundary.
        (
            "TamminScraper",
            [
                (
                    "Agenda",
                    "25.03.2021 Ordinary Council Meeting Agenda",
                    "25032021-ordinary-council-meeting-agenda.pdf",
                ),
                (
                    "Minutes",
                    "25.03.2021Ordinary Council Meeting",
                    "25032021ordinary-confirmed-council-meeting.pdf",
                ),
            ],
            "25032021-ordinary-council-meeting-agenda.pdf",
            "25032021ordinary-confirmed-council-meeting.pdf",
        ),
        # Tammin, September 2026: other bodies' minutes filed among the
        # agenda's attachments are not the meeting's minutes.
        (
            "TamminScraper",
            [
                (
                    "Agenda",
                    "September 2026 Ordinary Council Meeting Agenda 30.09.2026",
                    "september-2026-ordinary-council-meeting-agenda-30092026.pdf",
                ),
                ("Agenda", "SOT BFAC Minutes September 2026", "sot-bfac-minutes.pdf"),
                (
                    "Agenda",
                    "Audit Risk and Improvement Committee Minutes- September 2026",
                    "aric-minutes.pdf",
                ),
                (
                    "Minutes",
                    "September 2026 Ordinary Council Meeting Unconfirmed Minutes 30.09",
                    "september-2026-ordinary-council-meeting-minutes-30092026.pdf",
                ),
            ],
            "september-2026-ordinary-council-meeting-agenda-30092026.pdf",
            "september-2026-ordinary-council-meeting-minutes-30092026.pdf",
        ),
    ],
)
def test_pick_documents(class_name, links, agenda, minutes):
    picked = SCRAPER_REGISTRY[class_name]._pick_documents(
        [(group, label, f"{_PAGE}/documents/{name}") for group, label, name in links]
    )
    assert picked == (f"{_PAGE}/documents/{agenda}", f"{_PAGE}/documents/{minutes}")


@pytest.mark.parametrize(
    "class_name, heading, type_slug, labels, expected",
    [
        (
            "MukinbudinScraper",
            "8. September 2026 Ordinary Meeting of Council",
            "ordinary-council-meeting",
            {"ordinary-council-meeting": "Ordinary Council Meeting"},
            "Ordinary Council Meeting",
        ),
        (
            "MukinbudinScraper",
            "1. Annual Electors Meeting February 2026",
            "special-council-meeting",
            {"special-council-meeting": "Special Council Meeting"},
            "Annual Electors Meeting",
        ),
        (
            "WanderingScraper",
            "September Ordinary Council Meeting",
            "ordinary-council-meeting",
            {"ordinary-council-meeting": "Ordinary Council Meeting"},
            "Ordinary Council Meeting",
        ),
        (
            "WanderingScraper",
            "February Special Council Meeting",
            "special-council-meeting",
            {"special-council-meeting": "Special Council Meeting"},
            "Special Council Meeting",
        ),
        # Cue's one-off type, labelled with the meeting's own date and a
        # double space.
        (
            "CueScraper",
            "Ordinary Council Meeting  21 April 2026",
            "ordinary-council-meeting-21-april-2026",
            {
                "ordinary-council-meeting-21-april-2026": "Ordinary Council Meeting 21 April 2026"
            },
            "Ordinary Council Meeting",
        ),
        (
            "CueScraper",
            "Annual Meeting of Electors 2025",
            "annual-meeting-of-electors",
            {"annual-meeting-of-electors": "Annual Meeting of Electors"},
            "Annual Meeting of Electors",
        ),
        # Wyalkatchem's type labels are "Ordinary" and "Special"; its
        # `type_names` say what they are.
        (
            "WyalkatchemScraper",
            "Special Meeting of Council 12 February 2026",
            "special",
            {"special": "Special"},
            "Special Council Meeting",
        ),
    ],
)
def test_name(class_name, heading, type_slug, labels, expected):
    scraper = SCRAPER_REGISTRY[class_name]
    labels = {**labels, **scraper.type_names}
    assert scraper._name(heading, type_slug, labels) == expected


def test_midnight_is_no_time():
    scraper = SCRAPER_REGISTRY["MenziesScraper"]
    date, time = scraper._parse_when("Thursday, December 17, 2020 - 12:00 AM")
    assert (date.isoformat(), time) == ("2020-12-17", None)


@pytest.mark.parametrize(
    "when, time",
    [
        # Tammin 22 April 2026 and Cue 21 November 2023: the agendas say pm.
        ("Wednesday, April 22, 2026 - 05:00 AM", "5:00 PM"),
        ("Tuesday, November 21, 2023 - 06:00 AM", "6:00 PM"),
        # Real morning starts are left alone.
        ("Thursday, March 18, 2020 - 08:45 AM", "8:45 AM"),
        ("Wednesday, September 23, 2026 - 10:30 AM", "10:30 AM"),
    ],
)
def test_small_hours_are_pm(when, time):
    assert SCRAPER_REGISTRY["TamminScraper"]._parse_when(when)[1] == time
