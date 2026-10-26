"""Tests for how LGA SA Funnelback documents become meetings.

The cassettes prove the scrapers work end to end, but a re-record would
accept any change in which document becomes "the agenda". These pin the
rules that exist because the councils' own metadata is wrong in specific,
recurring ways—each case below is taken from a real collection. They drive
`scraper()` through a playback fetcher, so they exercise the real entry
point, request URL included.
"""

import datetime
import html
import re

import pytest

from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.lgasa import (
    CRAWL_DELAY_SECONDS,
    DOCUMENT_ROOT,
    ArchiveListing,
    LGASAFunnelbackScraper,
    ResolveWithLGASAArchive,
)
from aus_council_scrapers.resolve import SoleSourceFailed
from tests.cassette import PlaybackFetcher, encode_failure

YEAR = 2025
LISTING = "https://www.example.sa.gov.au/agendas-and-minutes"


class _Scraper(LGASAFunnelbackScraper):
    listing_urls = (LISTING,)

    def __init__(self):
        super().__init__("example_sa", "SA", "https://www.example.sa.gov.au")


def doc(asset_id, date, title, committee="Council Meetings", filename="document.pdf"):
    """One listed document. `filename=None` lists it with no file, as Light's
    dead stubs are."""
    return {
        "asset_id": asset_id,
        "date": date,
        "title": title,
        "committee": committee,
        "filename": filename,
    }


def as_listing_page(documents, total=None):
    """The listing page as the councils render it, one `li` per document."""
    items = []
    for d in documents:
        shown = datetime.date.fromisoformat(d["date"]).strftime("%d %b %Y")
        url = (
            f"https://www.example.sa.gov.au/__data/assets/pdf_file/0001/"
            f"{d['asset_id']}/{d['filename']}"
            if d["filename"] is not None
            else ""
        )
        link = (
            "https://lgasa-search.lga.sa.gov.au/s/redirect?url=https%3A%2F%2F"
            "lgasa-web.squiz.cloud%2Fframework%2Ffunnelback%2F"
            f"push-click-tracking-redirect%3FpushAsset%3D{d['asset_id']}"
        )
        items.append(
            f"""<li class="result-item"><a class="result-item__link" href="{html.escape(link)}">
            <h2 class="result-item__heading">{html.escape(d["title"])}</h2>
            <div class="result-item__url">{html.escape(url)}</div></a>
            <div class="result-item__content"><div class="minutes-and-agendas-listing__doc-details">
            <span class="minutes-and-agendas-listing__committe">{html.escape(d["committee"])}</span>
            <span class="minutes-and-agendas-listing__meetingDate">{shown}</span>
            </div></div></li>"""
        )
    total = len(documents) if total is None else total
    return (
        f'<html><body><div class="minutes-and-agendas-listing">'
        f'<div class="result-info__results-count">1 - {len(documents)} of {total} results</div>'
        f'<ul>{"".join(items)}</ul></div></body></html>'
    )


def scrape(results, year=YEAR, scraper_class=None):
    scraper = (scraper_class or _Scraper)()
    scraper.years_filter = [year]
    url = scraper._page_url(LISTING)
    scraper.fetcher = PlaybackFetcher([[["selenium", url], as_listing_page(results)]])
    return [(r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()]


def url(asset_id):
    return f"{DOCUMENT_ROOT}/?a={asset_id}"


# What the councils' robots.txt disallows, as `Disallow: *?*query=` and
# `Disallow: *?*f.*%7C*=` match: any query string carrying `query=`, or a
# facet parameter (`f.<name>|<field>=`, with the bar raw or encoded).
_DISALLOWED = re.compile(r"\?.*query=|\?.*f\.[^=]*(?:%7C|\|)[^=]*=", re.IGNORECASE)


class _ListingSite(Fetcher):
    """Serves listing pages by URL and records requests and waits."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []
        self.slept = []

    def get_selenium_driver(self):
        raise NotImplementedError

    def fetch_with_requests(self, url, method="GET", **kwargs):
        raise NotImplementedError

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        self.requested.append(url)
        return self.pages[url]

    def sleep(self, seconds):
        self.slept.append(seconds)


def test_a_full_history_run_pages_the_bare_listing_within_robots_txt():
    # No year is wanted that the unsorted tail could hide (see
    # NEWEST_UNSORTED_YEAR), so the whole listing is read: two pages, 20 s
    # apart, at the listing's own path with only the size and pager added.
    first = [doc(1, "2026-03-01", "Council Agenda 1 March 2026")]
    second = [doc(2, "2021-03-02", "Council Minutes 2 March 2021")]
    scraper = _Scraper()
    site = _ListingSite(
        {
            f"{LISTING}?num_ranks=500": as_listing_page(first, total=2),
            f"{LISTING}?num_ranks=500&start_rank=2": as_listing_page(second, total=2),
        }
    )
    scraper.fetcher = site
    meetings = scraper.scraper()

    assert site.requested == [
        f"{LISTING}?num_ranks=500",
        f"{LISTING}?num_ranks=500&start_rank=2",
    ]
    assert not [u for u in site.requested if _DISALLOWED.search(u)]
    assert site.slept == [pytest.approx(CRAWL_DELAY_SECONDS, abs=1)]
    assert [(m.date, m.agenda_url, m.minutes_url) for m in meetings] == [
        ("2026-03-01", url(1), None),
        ("2021-03-02", None, url(2)),
    ]


def test_a_current_year_run_stops_at_the_first_page_past_that_year():
    # Production asks for one year; the first page reaches back before it,
    # so the second page of a 1,000-document listing is never requested.
    page = [
        doc(1, "2026-03-01", "Council Agenda 1 March 2026"),
        doc(2, "2025-12-01", "Council Agenda 1 December 2025"),
    ]
    scraper = _Scraper()
    scraper.years_filter = [2026]
    site = _ListingSite({f"{LISTING}?num_ranks=500": as_listing_page(page, total=1000)})
    scraper.fetcher = site
    meetings = scraper.scraper()

    assert site.requested == [f"{LISTING}?num_ranks=500"]
    assert site.slept == []
    assert [m.date for m in meetings] == ["2026-03-01"]


def test_the_title_decides_and_attachments_are_never_the_agenda():
    # Gawler, 25 Nov 2025: an attachment bundle titled as an agenda item sits
    # beside the agenda, uploaded first. Prospect, 26 Aug 2025: minutes that
    # were filed under the Agendas category.
    results = [
        doc(
            1901940,
            "2025-11-25",
            "25-11-2025 Attachments1-3 Agenda Item 9.11",
        ),
        doc(1901942, "2025-11-25", "25-11-2025- Council Agenda"),
        doc(
            1903894,
            "2025-11-25",
            "25-11-2025 - Supplementary Council Agenda",
        ),
        doc(
            1860193,
            "2025-08-26",
            "Ordinary Council Meeting - MINUTES - 26 August 2025 - PUBLIC",
        ),
        doc(
            1857789,
            "2025-08-26",
            "Ordinary Council Meeting - Agenda - 26 August 2025",
        ),
    ]
    assert scrape(results) == [
        ("2025-11-25", "Council Meeting", url(1901942), None),
        ("2025-08-26", "Council Meeting", url(1857789), url(1860193)),
    ]


def test_cancelled_meetings_and_word_documents_are_dropped():
    results = [
        doc(
            1889647,
            "2025-11-13",
            "13-11-2025 - Notice of Cancellation - Council Assessment Panel",
            "Council Assessment Panel",
        ),
        doc(
            1523754,
            "2025-11-23",
            "Access and Inclusion Advisory Group - Agenda",
            "Access Group",
            filename="Access-and-Inclusion-Advisory-Group-Agenda.docx",
        ),
        doc(1, "2025-03-01", "Council Agenda 1 March 2025"),
    ]
    assert scrape(results) == [("2025-03-01", "Council Meeting", url(1), None)]


def test_an_agm_on_the_night_of_a_council_meeting_is_its_own_meeting():
    # Derwent Valley files both under one committee and one date.
    committee = "Council Agenda and Minutes"
    results = [
        doc(1724612, "2025-12-10", "10 December 2025 - AGM Agenda", committee),
        doc(1724798, "2025-12-10", "10 December 2025 - Agenda", committee),
        doc(
            1763373,
            "2025-12-10",
            "10 December 2025 - Council Meeting Minutes",
            committee,
        ),
        doc(
            1909265,
            "2025-12-10",
            "10 December 2025 - Unconfirmed AGM Minutes",
            committee,
        ),
    ]
    assert scrape(results) == [
        ("2025-12-10", "Council Meeting", url(1724798), url(1763373)),
        ("2025-12-10", "Annual General Meeting", url(1724612), url(1909265)),
    ]


def test_one_meeting_with_inconsistent_titles_is_not_split():
    # Gawler: "Council Agenda.PDF" pairs with "Council Minutes Special.PDF".
    results = [
        doc(930436, "2025-07-13", "13-07-2025 Council Agenda.PDF"),
        doc(932777, "2025-07-13", "13-07-2025 Council Minutes Special.PDF"),
    ]
    assert scrape(results) == [
        ("2025-07-13", "Special Council Meeting", url(930436), url(932777)),
    ]


def test_a_misdated_agenda_rejoins_its_minutes_on_the_date_both_titles_state():
    # Campbelltown dated its 21 July council agenda the 20th.
    results = [
        doc(2014966, "2025-07-20", "Council Agenda - 21 July 2025", "Council"),
        doc(
            2018141,
            "2025-07-21",
            "Council Minutes - 21 July 2025",
            "Council",
        ),
    ]
    assert scrape(results) == [
        ("2025-07-21", "Council Meeting", url(2014966), url(2018141)),
    ]


def test_a_placeholder_date_gives_way_to_the_date_in_the_title():
    # 1 January means nobody set the date. Gawler's CAP minutes of 10 June
    # 2021 were filed that way with no committee or category, and must land
    # on the CAP meeting, not on an invented council meeting on 1 January. A
    # title stating another year is a stray old upload and is dropped.
    cap = "Council Assessment Panel"
    results = [
        doc(
            909800,
            "2021-06-10",
            "10-06-2021 - Council Assessment Panel - Agenda",
            cap,
        ),
        doc(
            916604,
            "2021-01-01",
            "10-06-2021 - Council Assessment Panel Minutes",
            "",
        ),
        doc(
            219526,
            "2021-01-01",
            "27-04-2010 Council Agenda - Item 12.4 - Gawler East Separate Rate Review",
        ),
    ]
    assert scrape(results, year=2021) == [
        ("2021-06-10", cap, url(909800), url(916604)),
    ]


def test_skipped_committees_produce_nothing():
    class _Skipping(_Scraper):
        skip_committees = frozenset({"ERA Water"})

    results = [
        doc(5, "2025-05-05", "ERA Water Board Agenda 5 May 2025", "ERA Water"),
        doc(6, "2025-05-06", "Council Minutes 6 May 2025"),
    ]
    assert scrape(results, scraper_class=_Skipping) == [
        ("2025-05-06", "Council Meeting", None, url(6)),
    ]


def test_whole_documents_released_or_rescheduled_are_kept_but_single_items_are_not():
    # Port Adelaide Enfield re-uploaded its 11 July 2023 agenda and minutes
    # whole, titled "Released", once the confidential items were; and the
    # 2 March audit agenda names the rescheduled meeting. A released single
    # item and a notice of rescheduling are still never the agenda.
    full = "Full Council"
    audit = "Audit and Risk Committee"
    results = [
        doc(
            1430476,
            "2023-07-11",
            "11 July 2023 Agenda for Ordinary Council Meeting - Released",
            full,
        ),
        doc(
            1435246,
            "2023-07-11",
            "11 July 2023 Minutes for Ordinary Council Meeting Released",
            full,
        ),
        doc(
            1299998,
            "2023-03-02",
            "2 March 2023 Agenda for Rescheduled Audit and Risk Committee Meeting",
            audit,
        ),
        doc(
            1305491,
            "2023-03-02",
            "2 March 2023 Minutes for Audit and Risk Committee Meeting",
            audit,
        ),
        doc(
            1528120,
            "2023-09-15",
            "Confidential Council Minutes - 5 September 2023 - Item 9 1 - Motion on Notice - Released",
        ),
        doc(
            1065406,
            "2023-12-01",
            "Notice - Rescheduling of CAP Meeting - 1 December 2023 to 8 December 2023",
            "Council Assessment Panel",
        ),
    ]
    assert scrape(results, year=2023) == [
        ("2023-07-11", "Council Meeting", url(1430476), url(1435246)),
        ("2023-03-02", audit, url(1299998), url(1305491)),
    ]


def test_a_readable_pdf_beats_a_dead_stub_with_the_same_title():
    # Light filed "Council Agenda - 28 April 2020" twice; the older asset is
    # a 404 stub, listed with no file.
    results = [
        doc(652051, "2020-04-28", "Council Agenda - 28 April 2020", filename=None),
        doc(1100715, "2020-04-28", "Council Agenda - 28 April 2020"),
        doc(657672, "2020-04-28", "Council Minutes - 28 April 2020"),
    ]
    assert scrape(results, year=2020) == [
        ("2020-04-28", "Council Meeting", url(1100715), url(657672)),
    ]


@pytest.mark.parametrize(
    "year, results, expected",
    [
        pytest.param(
            2022,
            [
                doc(
                    1119395,
                    "2022-03-15",
                    "15-03-2022 Council Agenda Special Motions on Notice.PDF",
                ),
                doc(
                    1119400,
                    "2022-03-15",
                    "15-03-2022 Council Agenda Special Budget.PDF",
                ),
                doc(
                    1121731,
                    "2022-03-15",
                    "15-03-2022 Special Council Minutes - Heritage CAP.PDF",
                ),
                doc(
                    1121743,
                    "2022-03-15",
                    "15-03-2022 Special Council Minutes - Budget.PDF",
                ),
            ],
            {(1119395, 1121731), (1119400, 1121743)},
            id="paired-by-business",
        ),
        pytest.param(
            2024,
            [
                doc(
                    1544152,
                    "2024-02-15",
                    "15-02-2024 Second Special Council Meeting Agenda",
                ),
                doc(
                    1543281,
                    "2024-02-15",
                    "15-02-2024 Agenda Special Council",
                ),
                doc(
                    1548004,
                    "2024-02-15",
                    "15-02-2024 Minutes Special Council Meeting",
                ),
                doc(
                    1548032,
                    "2024-02-15",
                    "15-02-2024 - Minutes - Second Special Council Meeting",
                ),
            ],
            {(1543281, 1548004), (1544152, 1548032)},
            id="second-special",
        ),
    ],
)
def test_two_special_meetings_on_one_day_keep_their_own_documents(
    year, results, expected
):
    # Gawler, twice. Both meetings are kept, and neither borrows the other's
    # agenda or minutes.
    meetings = scrape(results, year=year)
    assert {name for _, name, _, _ in meetings} == {"Special Council Meeting"}
    assert {(a, m) for _, _, a, m in meetings} == {
        (url(a), url(m)) for a, m in expected
    }


def test_agenda_and_minutes_filed_days_apart_under_conflicting_titles_are_joined():
    # Derwent Valley: the minutes of 22 August 2024 are filed and titled the
    # 26th (the PDF says 22 August). The agenda's date wins.
    committee = "Council Agenda and Minutes"
    results = [
        doc(1661622, "2024-08-22", "22 August 2024 - Agenda", committee),
        doc(
            1685972,
            "2024-08-26",
            "26 August 2024 - Council Meeting Minutes",
            committee,
        ),
        doc(1700000, "2024-09-19", "19 September 2024 - Agenda", committee),
    ]
    assert scrape(results, year=2024) == [
        ("2024-09-19", "Council Meeting", url(1700000), None),
        ("2024-08-22", "Council Meeting", url(1661622), url(1685972)),
    ]


class _NoticeCommittee(_Scraper):
    notice_committees = frozenset({"Informal Gatherings"})


@pytest.mark.parametrize(
    "year, results, expected, scraper_class",
    [
        pytest.param(
            2026,
            [
                doc(
                    2057442,
                    "2026-10-12",
                    "12-10-2026 - Gawler Business & Economic Development Committee",
                    "Gawler Business and Economic Development Committee",
                    "12-10-2026-GBEDC-Agenda.PDF",
                ),
                doc(
                    2060717,
                    "2026-10-12",
                    "12-10-2026 - Gawler Business & Economic Development Committee Minutes",
                    "Gawler Business and Economic Development Committee",
                ),
            ],
            [(url(2057442), url(2060717))],
            None,
            id="file-name-says-agenda",
        ),
        pytest.param(
            2020,
            [
                doc(
                    713243,
                    "2020-07-21",
                    "21-07-2020 - Council Assessment Panel",
                    "Council Assessment Panel",
                    "CAP_20200721_AGN_2347.pdf",
                ),
                doc(
                    718928,
                    "2020-07-21",
                    "21-07-2020 Council Assessment Panel Minutes",
                    "Council Assessment Panel",
                ),
            ],
            [(url(713243), url(718928))],
            None,
            id="file-name-abbreviation",
        ),
        pytest.param(
            2022,
            [
                doc(
                    1102592,
                    "2022-02-14",
                    "14-02-2022 IES Notice of meeting.pdf",
                    "Infrastructure and Environmental Services Committee",
                    "14-02-2022-IES-Notice-of-meeting.pdf",
                ),
            ],
            [(url(1102592), None)],
            None,
            id="notice-of-meeting-is-the-agenda",
        ),
        pytest.param(
            2023,
            [
                doc(
                    1484339,
                    "2023-10-12",
                    "Notice of Information Session - 12 October 2023",
                    "Council Meetings",
                    "20231012-Notice-of-Information-Session.pdf",
                ),
                doc(1484400, "2023-10-24", "Council Agenda - 24 October 2023"),
            ],
            [(url(1484400), None)],
            None,
            id="information-session-is-not-a-council-meeting",
        ),
        pytest.param(
            2021,
            [
                # Filed alone: its agenda was filed under the next day.
                doc(
                    856490,
                    "2021-03-02",
                    "Councillor Information & Workshop Session - Notes - 02 March 2021",
                    "Councillor Information and Workshop Session",
                ),
            ],
            [(None, url(856490))],
            None,
            id="notes-are-the-minutes",
        ),
        pytest.param(
            2024,
            [
                doc(
                    1618567,
                    "2024-06-11",
                    "11 June 2024 - Ordinary Council Meeting",
                    "Full Council",
                    "Ordinary-Council-Meeting-11-June-2024-Public.pdf",
                ),
                doc(
                    1622452,
                    "2024-06-11",
                    "11 June 2024 - Minutes - Ordinary Council Meeting",
                    "Full Council",
                ),
            ],
            [(url(1618567), url(1622452))],
            None,
            id="bare-meeting-title-beside-minutes-is-the-agenda",
        ),
        pytest.param(
            2021,
            [
                doc(887240, "2021-05-04", "04-05-2021 Special Council Agenda"),
                doc(
                    890932,
                    "2021-05-04",
                    "04-05-2021 Special Council Meeting.pdf",
                    filename="04-05-2021-Special-Council-Meeting.pdf",
                ),
            ],
            [(url(887240), url(890932))],
            None,
            id="bare-meeting-title-beside-agenda-is-the-minutes",
        ),
        pytest.param(
            2020,
            [
                doc(
                    580382,
                    "2020-03-27",
                    "Updated Terms of Reference - Adopted 27 March 2020",
                    "Council Assessment Panel",
                ),
                doc(
                    580371,
                    "2020-03-27",
                    "Council Assessment Panel - Special Meeting - Minutes - 27 March 2020",
                    "Council Assessment Panel",
                ),
            ],
            [(None, url(580371))],
            None,
            id="a-paper-naming-no-sitting-is-never-the-agenda",
        ),
        pytest.param(
            2023,
            [
                doc(
                    1291450,
                    "2023-02-09",
                    "Elected Member Briefing Session Notice 9 February 2023",
                    "Informal Gatherings",
                    "Elected-Member-Briefing-Session-Notice-9-Feb-2023.pdf",
                ),
            ],
            [(url(1291450), None)],
            _NoticeCommittee,
            id="a-notice-committee-files-only-agendas",
        ),
    ],
)
def test_documents_whose_title_does_not_name_their_kind(
    year, results, expected, scraper_class
):
    # The listing page shows no document category, so these are decided by
    # file name, by notice and notes wording, or by the meeting's other
    # document. Each case is a real document from these collections.
    meetings = scrape(results, year=year, scraper_class=scraper_class)
    assert [(a, m) for _, _, a, m in meetings] == expected


def test_an_agenda_titled_with_another_date_does_not_split_the_meeting():
    # Derwent Valley's 16 July 2020 council meeting carries the Local
    # Government Association of Tasmania's AGM agenda, titled 22 July. It is
    # an attachment, not a second sitting of the council.
    committee = "Council Agenda and Minutes"
    results = [
        doc(712900, "2020-07-16", "16 July 2020 - Council Agenda", committee),
        doc(
            712942,
            "2020-07-16",
            "22-July-2020-AGM-Agenda.pdf",
            committee,
            "22-July-2020-AGM-Agenda.pdf",
        ),
        doc(715000, "2020-07-16", "16 July 2020 - Council Minutes", committee),
    ]
    assert scrape(results, year=2020) == [
        ("2020-07-16", "Council Meeting", url(712900), url(715000)),
    ]


def test_a_run_where_every_request_failed_raises_instead_of_returning_nothing():
    scraper = _Scraper()
    scraper.years_filter = [YEAR]
    failure = encode_failure(TimeoutError("challenge did not clear"))
    scraper.fetcher = PlaybackFetcher(
        [[["selenium", scraper._page_url(LISTING)], failure]]
    )
    with pytest.raises(RuntimeError, match="every listing page request failed"):
        scraper.scraper()


# --- A Resolve council's archive on LGA SA listing pages ------------------

COUNCIL_PAGE = "https://www.example.sa.gov.au/council-meetings"
PANEL_PAGE = "https://www.example.sa.gov.au/council-assessment-panel"


class _MovedToResolve(ResolveWithLGASAArchive):
    """Council moved to Resolve on 22 September 2026; the panel never did."""

    tenant = "example"
    resolve_from = datetime.date(2026, 9, 22)
    archive_listings = (
        ArchiveListing(COUNCIL_PAGE, until=resolve_from),
        ArchiveListing(PANEL_PAGE, keep=re.compile(r"Assessment Panel")),
    )

    def __init__(self):
        super().__init__("example_sa", "SA")


class _ResolveAndListings(_ListingSite):
    """Listing pages through Chrome, and a Resolve tenant with no events."""

    def fetch_with_requests(self, url, method="GET", **kwargs):
        assert url.startswith("https://api.resolve.red/"), url
        return '{"results": [], "totalPages": 1}'


def _archive_run(year, pages):
    scraper = _MovedToResolve()
    scraper.years_filter = [year]
    site = _ResolveAndListings(pages)
    scraper.fetcher = site
    return scraper.scraper(), site


def test_a_resolve_council_reads_each_archive_listing_only_while_it_is_needed():
    # Production asks for one year. In the year of the move both listings
    # are read, 20 s apart, and the copy of a Council meeting held after the
    # move—Resolve's to report—is dropped, as is a Council agenda filed on
    # the panel's page.
    council = [
        doc(1, "2026-10-13", "Council Agenda 13 October 2026"),
        doc(2, "2026-09-08", "Council Agenda 8 September 2026"),
        doc(3, "2025-12-09", "Council Agenda 9 December 2025"),
    ]
    panel = [
        doc(
            4, "2026-09-23", "CAP Agenda 23 September 2026", "Council Assessment Panel"
        ),
        doc(
            5,
            "2026-09-23",
            "Agenda - Ordinary Council Meeting 23 September 2026",
            "Council Assessment Panel",
        ),
        doc(6, "2025-12-01", "CAP Agenda 1 December 2025", "Council Assessment Panel"),
    ]
    pages = {
        f"{COUNCIL_PAGE}?num_ranks=500": as_listing_page(council, total=900),
        f"{PANEL_PAGE}?num_ranks=500": as_listing_page(panel, total=900),
    }

    meetings, site = _archive_run(2026, pages)

    assert [(m.date, m.name, m.agenda_url) for m in meetings] == [
        ("2026-09-08", "Council Meeting", url(2)),
        ("2026-09-23", "Council Assessment Panel", url(4)),
    ]
    assert site.requested == [
        f"{COUNCIL_PAGE}?num_ranks=500",
        f"{PANEL_PAGE}?num_ranks=500",
    ]
    assert site.slept == [pytest.approx(CRAWL_DELAY_SECONDS, abs=1)]

    # The year after the move, the Council page is not opened at all.
    _, site = _archive_run(2027, pages)
    assert site.requested == [f"{PANEL_PAGE}?num_ranks=500"]


def test_a_body_that_never_moved_fails_the_council_when_its_listing_fails():
    # The Council page loads, so before this the panel was dropped with a
    # warning and the council reported success. The panel is on no other
    # source, so its listing failing is the council failing.
    council = [doc(2, "2026-09-08", "Council Agenda 8 September 2026")]
    pages = {f"{COUNCIL_PAGE}?num_ranks=500": as_listing_page(council, total=900)}

    with pytest.raises(SoleSourceFailed, match="council-assessment-panel"):
        _archive_run(2026, pages)
