"""CouncilConnect: the eight councils added with the B-CC-1 base patches.

The replay tests pin each council's whole output. What they do not pin is
what one production night costs, and which rules decide a document when the
council happens to upload them in a lucky order. A later re-record would
carry a regression in either straight into the fixture, so both are held
here: the one-year bound as test_councilconnect.py holds it for the earlier
councils, and the document and name choices as cases taken from the sites.
"""

import datetime
import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths

REQUEST_BUDGET = 20

B_CC_1_SCRAPERS = [
    "AlbanyScraper",
    "NorthamScraper",
    "LeonoraScraper",
    "YorkScraper",
    "MooraScraper",
    "WestoniaScraper",
    "DundasScraper",
    "KoordaScraper",
]


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


@pytest.mark.parametrize("class_name", B_CC_1_SCRAPERS)
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name):
    # Albany, Leonora, York and Dundas read the all-types listing and skip
    # other types before fetching (`type_listings = False`); a change that
    # fetched every type's meeting pages would blow the budget here.
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


_PAGE = "https://x/council-meetings/ordinary-council-meeting/m/1"


@pytest.mark.parametrize(
    "meeting, links, agenda, minutes",
    [
        # Northam: every label starts with a dotted date, which is not a
        # report's item number.
        (
            "Ordinary Council Meeting - 17 December 2025",
            [
                ("Agenda", "2025.12.17 - AGENDA - Ordinary Council Meeting", "a.pdf"),
                ("Minutes", "2025.12.17 - MINUTES - Ordinary Council Meeting", "m.pdf"),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Northam, 28 January 2026: unpadded either way round, and the
        # minutes marked confirmed beat the ones that say neither.
        (
            "Ordinary Council Meeting - 28 January 2026",
            [
                ("Agenda", "28.1.2026 - AGENDA - Ordinary Council Meeting", "a.pdf"),
                ("Minutes", "2026.1.28 - MINUTES - Ordinary Council Meeting", "u.pdf"),
                (
                    "Minutes",
                    "2026.1.28 - MINUTES - Ordinary Council Meeting (CONFIRMED)",
                    "c.pdf",
                ),
            ],
            "a.pdf",
            "c.pdf",
        ),
        # Leonora, 16 July 2024: "MINS" under a vague group.
        (
            "Ordinary Council Meeting - 16th July, 2024",
            [
                ("Agenda", "AGJuly2024 Final", "a.pdf"),
                ("Downloads", "Confirmed MINS OCM 16 July 2024", "m.pdf"),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # ...while a real item number still marks a single report.
        (
            "Ordinary Council Meeting",
            [
                ("Agenda", "Agenda", "a.pdf"),
                ("Minutes", "10.2.2 Unconfirmed Minutes - Audit Committee", "x.pdf"),
            ],
            "a.pdf",
            None,
        ),
        # Westonia, March 2025: the Audit Committee's papers on the Ordinary
        # meeting's page, here uploaded first.
        (
            "March Ordinary Council Meeting",
            [
                ("Agenda", "0325 Audit Agenda March 2025", "audit-a.pdf"),
                ("Agenda", "0325 March Agenda 2025", "a.pdf"),
                ("Minutes", "0325 Minutes Audit March 2025", "audit-m.pdf"),
                ("Minutes", "0325 Minutes March 2025", "m.pdf"),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Moora, 10 December 2025, and Westonia's electors' agenda.
        (
            "10 December 2025 - Ordinary Meeting of Council",
            [
                ("Agendas", "Briefing Session Agenda - 10 December 2025", "b.pdf"),
                ("Agendas", "0226 Agenda Annual General Meeting of Electors", "e.pdf"),
                ("Agendas", "Ordinary Council Meeting Agenda - 10 December", "a.pdf"),
            ],
            "a.pdf",
            None,
        ),
        # A committee meeting keeps its own committee papers.
        (
            "Audit and Risk Committee Meeting - 18 March 2025",
            [
                ("Agenda", "Agenda for the Audit and Risk Committee", "a.pdf"),
                (
                    "Minutes",
                    "Confirmed Minutes of the Audit and Risk Committee",
                    "m.pdf",
                ),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Dundas: the previous meeting's minutes, filed as an appendix, are
        # not this meeting's minutes when its own are not up yet.
        (
            "Ordinary Council Meeting",
            [
                (
                    "Document",
                    "App1_Unconfirmed Minutes - 29 September 2026 OCM",
                    "p.pdf",
                ),
                ("Agenda", "Agenda_17 October 2026 OCM", "a.pdf"),
            ],
            "a.pdf",
            None,
        ),
        # Northam, 26 November 2025: only the group says these are minutes,
        # and the confirmed pair still wins.
        (
            "Ordinary Council Meeting",
            [
                (
                    "Minutes",
                    "Ordinary Council Meeting - PART 1 PUBLIC (UNCONFIRMED)",
                    "u.pdf",
                ),
                (
                    "Minutes",
                    "Ordinary Council Meeting - PART 1 PUBLIC (CONFIRMED)",
                    "c.pdf",
                ),
            ],
            None,
            "c.pdf",
        ),
        # York, 26 August 2025: "Uncomfirmed" is unconfirmed.
        (
            "Ordinary Council Meeting",
            [
                (
                    "Minutes",
                    "Uncomfirmed Minutes and Appendices - 26 August 2025",
                    "u.pdf",
                ),
                (
                    "Minutes",
                    "Confirmed Minutes and Appendices - 26 August 2025",
                    "c.pdf",
                ),
            ],
            None,
            "c.pdf",
        ),
        # Albany's "_v2" and York's "Updated" are revisions of the agenda.
        (
            "Ordinary Council Meeting",
            [
                ("Agenda", "ocm_agenda_oct25", "ocm_agenda_oct25.pdf"),
                ("Agenda", "ocm_agenda_oct25_v2", "ocm_agenda_oct25_v2.pdf"),
            ],
            "ocm_agenda_oct25_v2.pdf",
            None,
        ),
        (
            "Ordinary Council Meeting",
            [
                ("Agenda", "Agenda-and-Appendices-OCM-24-March-2026 Original", "o.pdf"),
                ("Agenda", "Agenda & Appendices OCM 24 March 2026 Updated", "u.pdf"),
            ],
            "u.pdf",
            None,
        ),
    ],
)
def test_pick_documents(meeting, links, agenda, minutes):
    scraper = SCRAPER_REGISTRY["WestoniaScraper"]
    picked = scraper._pick_documents(
        [(group, label, f"{_PAGE}/documents/{name}") for group, label, name in links],
        meeting_name=meeting,
    )
    assert picked == (
        agenda and f"{_PAGE}/documents/{agenda}",
        minutes and f"{_PAGE}/documents/{minutes}",
    )


@pytest.mark.parametrize(
    "heading, type_slug, label, expected",
    [
        # Leonora: the comma before the year, a bare year, a plural type.
        (
            "Ordinary Council Meeting - 21st October, 2025",
            "ordinary-council-meetings",
            "Ordinary Council Meetings",
            "Ordinary Council Meeting",
        ),
        (
            "Annual Electors Meeting, 2025",
            "electors-meeting",
            "Electors Meeting",
            "Annual Electors Meeting",
        ),
        # Westonia: a month with no day.
        (
            "February Ordinary Council Meeting",
            "ordinary-meeting",
            "Ordinary Meeting",
            "Ordinary Council Meeting",
        ),
        # York: the type worded the other way round, with the meeting's
        # business after it.
        (
            "Special Council Meeting - 2025/26 Budget Adoption",
            "special-meeting-of-council",
            "Special Meeting of Council",
            "Special Meeting of Council",
        ),
    ],
)
def test_name_is_the_meeting_type(heading, type_slug, label, expected):
    scraper = SCRAPER_REGISTRY["WestoniaScraper"]
    assert scraper._name(heading, type_slug, {type_slug: label}) == expected


def test_documents_naming_another_date_are_tried_last():
    # Albany, 3 February 2021: two earlier electors' meetings' minutes are
    # listed ahead of this meeting's own.
    scraper = SCRAPER_REGISTRY["WestoniaScraper"]
    links = [
        (
            "Minutes",
            "Special Electors Meeting - Minutes - 8 December 2020",
            "dec20.pdf",
        ),
        (
            "Minutes",
            "Annual Electors Meeting - Minutes - 16 December 2019",
            "dec19.pdf",
        ),
        ("Minutes", "electors meeting_minutes_3feb21_confirmed", "3feb21.pdf"),
    ]
    _, minutes = scraper._pick_documents(
        [(g, label, f"{_PAGE}/documents/{name}") for g, label, name in links],
        meeting_name="Annual Electors Meeting - 03 February 2021",
        date=datetime.date(2021, 2, 3),
    )
    assert minutes == f"{_PAGE}/documents/3feb21.pdf"
