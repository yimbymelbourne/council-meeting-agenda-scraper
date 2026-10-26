"""The nine CouncilConnect councils on the filtered all-types listing.

`FilteredListingCouncilConnectScraper` reads /council-meetings/past/<year>
and keeps its `meeting_types` from it, because some sites' per-type year
pages drop meetings or 404 (see councilconnect_filtered.py). The cassettes
replay the full history unfiltered, so they say nothing about what one
production night costs. These replay them with the single year production
passes and check that it fetches only that year, stays within the request
budget, and still finds every meeting of that year.

Below that: the clean-ups the subclass adds, each pinned to the case on a
council's site that needed it, and Beverley's document-library fallback.
"""

import datetime
import json

import pytest

from aus_council_scrapers import clock
from aus_council_scrapers.base import SCRAPER_REGISTRY
from tests.cassette import PlaybackFetcher, cassette_paths
from tests.test_councilconnect import VERSIONED_DOCUMENT

# One production year should stay within ~20 requests (see AGENTS.md on the
# 600 s budget).
REQUEST_BUDGET = 20

SCRAPERS = [
    "CoolgardieScraper",
    "ExmouthScraper",
    "MerredinScraper",
    "TiwiIslandsScraper",
    "RavensthorpeScraper",
    "BoddingtonScraper",
    "BeverleyScraper",
    "ChapmanValleyScraper",
    "DalwallinuScraper",
]


class _Counting(PlaybackFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs):
        self.urls.append(url)
        return super().fetch_with_requests(url, method, **kwargs)


def _replay_one_year(class_name):
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
    return year, fetcher.urls, recorded, result


@pytest.mark.parametrize("class_name", SCRAPERS)
def test_one_year_fetches_only_that_year_and_loses_nothing(class_name):
    year, urls, recorded, result = _replay_one_year(class_name)

    other_years = [u for u in urls if "/past/" in u and f"/past/{year}" not in u]
    assert other_years == []
    # The all-types listing is the only listing read: a per-type page here
    # would mean the subclass stopped replacing them.
    assert all("/council-meetings/past/" in u for u in urls if "/past/" in u)
    assert len(urls) <= REQUEST_BUDGET
    assert [r.to_dict() for r in result] == [
        m for m in recorded if m["date"].startswith(str(year))
    ]


@pytest.mark.parametrize("class_name", SCRAPERS)
def test_only_council_meeting_types_are_emitted_or_fetched(class_name):
    scraper = SCRAPER_REGISTRY[class_name]
    _, urls, recorded, _ = _replay_one_year(class_name)

    fetched_types = {scraper.meeting_type_of(u) for u in urls} - {None}
    assert fetched_types <= set(scraper.meeting_types)
    assert {scraper.meeting_type_of(m["webpage_url"]) for m in recorded} <= set(
        scraper.meeting_types
    )


@pytest.mark.parametrize("class_name", SCRAPERS)
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


_PAGE = "https://x/council-meetings/ordinary-council-meeting/m/1"


@pytest.mark.parametrize(
    "links, agenda, minutes",
    [
        # Exmouth, 26 March 2026: the notice cancelling the Ordinary meeting
        # sits under its "Agenda" heading.
        (
            [("Agenda", "Notice of Cancellation OCM 26 March 2026", "notice.pdf")],
            None,
            None,
        ),
        # Ravensthorpe, 16 June 2026: the only agenda includes its late item.
        (
            [
                (
                    "Agenda",
                    "Agenda OCM 16.06.2026 - Final v2 Inc Late Item",
                    "agenda-ocm-16062026-final-v2-inc-late-item.pdf",
                ),
                ("Minutes", "Minutes OCM 16.06.2026", "minutes-ocm-16062026.pdf"),
            ],
            "agenda-ocm-16062026-final-v2-inc-late-item.pdf",
            "minutes-ocm-16062026.pdf",
        ),
        # A late item on its own is still not the agenda, beside one or not.
        (
            [
                ("Agenda", "Late Item 12.1", "late-item-12-1.pdf"),
                ("Agenda", "Agenda OCM", "agenda-ocm.pdf"),
            ],
            "agenda-ocm.pdf",
            None,
        ),
        ([("Agenda", "Late Item 12.1", "late-item-12-1.pdf")], None, None),
        # Coolgardie, 27 April 2021: the only agenda, a packet the base's
        # packet test misses for the ampersand.
        (
            [
                ("Minutes", "Confirmed Minutes - with attachments", "minutes.pdf"),
                (
                    "Downloads",
                    "OCM Agenda & Attachments 27 April 2021",
                    "ocm-agenda-and-attachments-27-april-2021.pdf",
                ),
            ],
            "ocm-agenda-and-attachments-27-april-2021.pdf",
            "minutes.pdf",
        ),
        # Chapman Valley, 15 August 2024: bare minutes beside the packet;
        # the packet is read only when there is nothing else.
        (
            [
                ("Agenda", "Ordinary Council Meeting Agenda - August 2024", "a.pdf"),
                (
                    "Minutes",
                    "Ordinary Council Meeting Minutes - August 2024 - Inline Attachments",
                    "m-inline-attachments.pdf",
                ),
                ("Minutes", "Ordinary Council Meeting Minutes - August 2024", "m.pdf"),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Merredin, 28 July 2020: the agenda under the Attachments heading,
        # beside an attachment that is another meeting's minutes.
        (
            [
                (
                    "Minutes",
                    "Minutes - Special Council Meeting - 28 July 2020",
                    "m.pdf",
                ),
                ("Attachments", "Attachment 7.1A - Minutes - 30 June 2020", "att.pdf"),
                (
                    "Attachments",
                    "Agenda - Special Council Meeting - 28 July 2020",
                    "a.pdf",
                ),
            ],
            "a.pdf",
            "m.pdf",
        ),
        # Exmouth, 2 February 2023: "and Attachment_" is a packet. The
        # underscore kept the base's packet test from ending the word.
        (
            [
                (
                    "Agenda",
                    "Special Council Meeting Agenda and Attachment_ 2 February 2023",
                    "scm-agenda-02-february-2023-inc-attach_website.pdf",
                ),
                (
                    "Minutes",
                    "Special Council Meeting Minutes and Attachment_ 2 February 2023",
                    "23-02-02-scm-minutes-inc-attach-website.pdf",
                ),
            ],
            "scm-agenda-02-february-2023-inc-attach_website.pdf",
            "23-02-02-scm-minutes-inc-attach-website.pdf",
        ),
        # An attachment whose label merely carries an underscore is still one.
        ([("Agenda", "Attachment_ 7.1 Agenda", "attachment-7-1.pdf")], None, None),
    ],
)
def test_pick_documents(links, agenda, minutes):
    scraper = SCRAPER_REGISTRY["RavensthorpeScraper"]
    picked = scraper._pick_documents(
        [(group, label, f"{_PAGE}/documents/{name}") for group, label, name in links]
    )
    assert picked == tuple(
        f"{_PAGE}/documents/{name}" if name else None for name in (agenda, minutes)
    )


@pytest.mark.parametrize(
    "heading, type_slug, expected",
    [
        # Merredin heads meetings with their month first; "September" was
        # enough to tip the similarity test and keep the month in the name.
        (
            "September Ordinary Council Meeting",
            "ordinary-council-meeting",
            "Ordinary Council Meeting",
        ),
        (
            "May Ordinary Council Meeting",
            "ordinary-council-meeting",
            "Ordinary Council Meeting",
        ),
        # A word short of the type's name, filed under that type.
        ("Special Meeting", "special-council-meeting", "Special Council Meeting"),
        # Filed under the Ordinary type, it keeps its own name.
        ("Special Meeting", "ordinary-council-meeting", "Special Meeting"),
        # Ravensthorpe's year-stamped 2020 type takes the plain name.
        (
            "Ordinary Council Meeting",
            "ordinary-council-meeting-2020",
            "Ordinary Council Meeting",
        ),
    ],
)
def test_names(heading, type_slug, expected):
    scraper = SCRAPER_REGISTRY["RavensthorpeScraper"]
    assert scraper._name(heading, type_slug, dict(scraper.meeting_types)) == expected


def test_other_types_cost_no_request():
    # A committee on the all-types listing is dropped on its URL alone.
    class _Refuses(PlaybackFetcher):
        def fetch_with_requests(self, url, method="GET", **kwargs):
            raise AssertionError(f"fetched {url}")

    scraper = SCRAPER_REGISTRY["DalwallinuScraper"]
    scraper.fetcher = _Refuses([], "dalwallinu")
    url = "https://www.dalwallinu.wa.gov.au/council-meetings/audit-committee/m/9"
    assert scraper._read_meeting(url, {}, (None, None)) is None


def test_cancelled_meeting_is_skipped_before_its_page_is_fetched():
    from bs4 import BeautifulSoup

    # Tiwi Islands, 23 April 2025: the page carries the agenda of the 16
    # April meeting it was replaced by.
    summary = BeautifulSoup(
        '<div class="council-meeting-summary"><h3>Ordinary Council Meeting'
        " CANCELLED</h3>"
        '<a href="/council-meetings/ordinary-council-meeting/ocm/170">View</a>'
        "</div>",
        "html.parser",
    ).div
    scraper = SCRAPER_REGISTRY["TiwiIslandsScraper"]
    assert (
        scraper._summary_meeting(summary, "https://x/past/2025", {}, 2025, set()) == []
    )


def test_merredin_notice_of_meeting_is_not_the_agenda():
    # 6 July 2021: a one-page notice under "Agenda", beside the minutes.
    scraper = SCRAPER_REGISTRY["MerredinScraper"]
    picked = scraper._pick_documents(
        [
            (
                "Agenda",
                "Notice of Special Council Meeting - 6 July 2021",
                f"{_PAGE}/documents/notice-of-meeting-special-council-meeting-6-july-2021.pdf",
            ),
            (
                "Minutes",
                "Minutes - Special Council Meeting - 6 July 2021",
                f"{_PAGE}/documents/special-council-meeting-minutes-6-july-2021.pdf",
            ),
        ]
    )
    assert picked == (
        None,
        f"{_PAGE}/documents/special-council-meeting-minutes-6-july-2021.pdf",
    )


def test_beverley_wrong_documents_are_replaced_or_dropped():
    scraper = SCRAPER_REGISTRY["BeverleyScraper"]
    result_path, _ = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = {m["date"]: m for m in json.load(f)}
    # /208's only paper is the 13 December 2022 agenda; no meeting sat on 13
    # October.
    assert "2022-10-13" not in recorded
    # The module's 26 March 2025 minutes are not a PDF; the library's are.
    assert recorded["2025-03-26"]["minutes_url"] == (
        "https://www.beverley.wa.gov.au/documents/2723/"
        "20250326-march-ordinary-council-meeting-minutes"
    )


def test_beverley_library_404_warns_for_a_year_under_way(caplog):
    import requests

    class _NotFound(PlaybackFetcher):
        def fetch_with_requests(self, url, method="GET", **kwargs):
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)

    scraper = SCRAPER_REGISTRY["BeverleyScraper"]
    previous = scraper.fetcher
    scraper.fetcher = _NotFound([], "beverley")
    scraper._library = {}
    try:
        with clock.frozen("2026-10-20"), caplog.at_level("INFO"):
            assert scraper._library_items(2027, "agendas") == []
            assert scraper._library_items(2026, "agendas") == []
    finally:
        scraper.fetcher = previous
        scraper._library = {}
    levels = {r.getMessage().rsplit("-", 1)[-1]: r.levelname for r in caplog.records}
    assert levels == {"2027": "INFO", "2026": "WARNING"}


def test_beverley_library_matches_only_the_exact_date_and_kind():
    scraper = SCRAPER_REGISTRY["BeverleyScraper"]
    base = "https://www.beverley.wa.gov.au/documents"
    scraper._library = {
        (2026, "agendas"): [
            ("20260225 February Ordinary Council Meeting Agenda", f"{base}/1/a"),
            ("20260225 February Ordinary Council Meeting Attachments", f"{base}/2/b"),
            ("20260311 Special Council Meeting Agenda", f"{base}/3/c"),
        ],
        (2026, "minutes"): [
            (
                "20260225 Recording One of February Ordinary Council Meeting Minutes",
                f"{base}/4/d",
            ),
            (
                "20260225 February Ordinary Council Meeting Unconfirmed Minutes",
                f"{base}/5/e",
            ),
            ("20260225 February Ordinary Council Meeting Minutes", f"{base}/6/f"),
        ],
    }
    feb = datetime.date(2026, 2, 25)
    assert scraper._library_document(feb, False, "agendas") == f"{base}/1/a"
    assert scraper._library_document(feb, False, "minutes") == f"{base}/6/f"
    # A special meeting on the same date is not the ordinary one.
    assert scraper._library_document(feb, True, "agendas") is None
    # A date one day out matches nothing.
    assert (
        scraper._library_document(datetime.date(2026, 2, 24), False, "agendas") is None
    )


@pytest.mark.parametrize(
    "class_name, date, time",
    [
        # Boddington's February 2024 date field is when the meeting was
        # entered; its papers say Thursday 15 February.
        ("BoddingtonScraper", "2024-02-15", None),
        # Dalwallinu's 25 February 2020 time was never filled in (12:00 AM).
        ("DalwallinuScraper", "2020-02-25", None),
        # A real start time is kept.
        ("BeverleyScraper", "2025-02-26", "3:00 PM"),
    ],
)
def test_entry_stamps_are_not_meeting_dates_or_times(class_name, date, time):
    scraper = SCRAPER_REGISTRY[class_name]
    result_path, _ = cassette_paths(scraper.council_name)
    with open(result_path) as f:
        recorded = json.load(f)
    assert [m["time"] for m in recorded if m["date"] == date] == [time]
    assert not any(m["date"] == "2024-02-23" for m in recorded)
