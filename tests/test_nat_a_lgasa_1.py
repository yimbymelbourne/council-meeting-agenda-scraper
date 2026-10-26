"""The corrections `RelabellingLGASAScraper` and Whyalla's audit page make.

Each case is a real document from the council named, reduced to the fields
that decide it. The cassettes show the councils' output end to end; these pin
the rule each correction exists for, so a re-record cannot quietly lose it.
"""

import re

import pytest

from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper
from aus_council_scrapers.scrapers.sa.whyalla import (
    AUDIT_COMMITTEE,
    AUDIT_PAGE,
    WhyallaScraper,
    _audit_documents,
)
from tests.cassette import PlaybackFetcher, encode_failure
from tests.test_lgasa import LISTING, as_listing_page, doc, url

PANEL = "https://www.example.sa.gov.au/assessment-panel"


class _Relabelling(RelabellingLGASAScraper):
    listing_urls = (LISTING,)

    def __init__(self):
        super().__init__("example_sa", "SA", "https://www.example.sa.gov.au")


def scrape(documents, year=2025, **settings):
    scraper = type("_Configured", (_Relabelling,), settings)()
    scraper.years_filter = [year]
    scraper.fetcher = PlaybackFetcher(
        [[["selenium", scraper._page_url(LISTING)], as_listing_page(documents)]]
    )
    return [(r.date, r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()]


def test_a_notice_of_adjournment_is_not_the_agenda():
    # Port Pirie, 17 February 2025: the meeting never sat for want of a
    # quorum, and the notice saying so had become its agenda.
    assert (
        scrape(
            [
                doc(
                    "1762884",
                    "2025-02-17",
                    "Notice of Adjournment - TLAP Consultative Committee Meeting "
                    "17 February 2025",
                    committee="TLAP Consultative Committee",
                    filename="Notice-of-Adjournment-of-Committee-Meeting-TLAP.pdf",
                )
            ]
        )
        == []
    )


def test_an_agenda_noting_the_adjournment_is_still_the_agenda():
    # Port Lincoln, 17 August 2026: the agenda as issued, retitled after.
    assert scrape(
        [
            doc(
                "2029097",
                "2026-08-17",
                "Agenda - 17 August 2026 - Meeting adjourned due to lack of quorum",
                committee="Council Meetings",
            ),
            doc(
                "2030861",
                "2026-08-17",
                "Public Notice - Adjournment of Ordinary Council meeting 17 August 2026",
                committee="Council Meetings",
            ),
        ],
        year=2026,
    ) == [("2026-08-17", "Council Meeting", url("2029097"), None)]


def test_a_revised_agenda_replaces_the_original():
    # Latrobe, 28 April 2025: 400 pages, then 416 under "Revised Agenda".
    assert scrape(
        [
            doc("1798673", "2025-04-28", "Agenda - 28 April 2025"),
            doc("1799116", "2025-04-28", "Revised Agenda - 28 April 2025"),
            doc("1801035", "2025-04-28", "Minutes - 28 April 2025"),
        ]
    ) == [("2025-04-28", "Council Meeting", url("1799116"), url("1801035"))]


def test_a_combined_agenda_and_minutes_fills_both_slots():
    # Port Augusta's Aboriginal Community Advisory Group, 3 February 2025:
    # one PDF, the agenda then that meeting's minutes.
    group = "Aboriginal Community Advisory Group"
    documents = [
        doc(
            "1860349",
            "2025-02-03",
            f"{group} Agenda & MInutes - 03/02/2025",
            committee=group,
        )
    ]
    assert scrape(documents) == []
    assert scrape(documents, combined_documents=True) == [
        ("2025-02-03", group, url("1860349"), url("1860349"))
    ]


def test_a_title_dated_committee_takes_the_date_in_the_title():
    # Port Lincoln files this notice under 3 February; the session was the
    # 9th, as the title and the notice inside both say.
    label = "Information/Briefing Sessions"
    assert scrape(
        [
            doc(
                "1931231",
                "2026-02-03",
                "9/2/2026 - Closed to Public - Elected Member Workshop",
                committee=label,
                filename="110722-INFORMATION-BRIEFING-SESSION-NOTICE.pdf",
            )
        ],
        year=2026,
        notice_committees=frozenset({label}),
        title_dated_committees=frozenset({label}),
        committee_names={label: "Information or Briefing Session"},
    ) == [("2026-02-09", "Information or Briefing Session", url("1931231"), None)]


def test_relabel_moves_one_bodys_notice_to_its_own_label():
    # Port Pirie filed this group's notice with its briefing sessions.
    group = "Access & Inclusion Reference Group Meetings"
    assert scrape(
        [
            doc(
                "1946128",
                "2026-02-24",
                "Notice of Access and Inclusion Reference Group Meeting 24 February 2026",
                committee="Information or Briefing Sessions",
                filename="1.-Notice-of-AIRG-Meeting-24-February-2026.pdf",
            )
        ],
        year=2026,
        relabel=(
            (
                "Information or Briefing Sessions",
                re.compile(r"Access and Inclusion Reference Group"),
                group,
            ),
        ),
        committee_names={group: "Access & Inclusion Reference Group"},
    ) == [("2026-02-24", "Access & Inclusion Reference Group", url("1946128"), None)]


def test_losing_one_of_several_listings_fails_the_run():
    # Murray Bridge's assessment panel is on a page of its own; a run that
    # lost it must not report the council's meetings alone as complete.
    class _TwoPages(_Relabelling):
        listing_urls = (LISTING, PANEL)

    scraper = _TwoPages()
    scraper.years_filter = [2025]
    scraper.fetcher = PlaybackFetcher(
        [
            [
                ["selenium", scraper._page_url(LISTING)],
                as_listing_page(
                    [doc("1", "2025-03-10", "Council Agenda 10 March 2025")]
                ),
            ],
            [
                ["selenium", scraper._page_url(PANEL)],
                encode_failure(TimeoutError("challenge did not clear")),
            ],
        ]
    )
    with pytest.raises(RuntimeError, match="assessment-panel"):
        scraper.scraper()


AUDIT_HTML = """<html><body>
<div class="mega-menu__item-row"><a href="https://www.whyalla.sa.gov.au/__data/assets/pdf_file/0041/1857857/Rules.pdf">Christmas Pageant Float Rules</a></div>
<main><div class="generic-list"><ul class="generic-list__list">
<li class="generic-list__item generic-list__file"><div class="generic-list__header"><div class="generic-list__right"><h3 class="generic-list__title">
<a href="https://www.whyalla.sa.gov.au/__data/assets/pdf_file/0029/2055458/PUBLIC-Agenda-Complete.pdf">Audit and Risk Committee Meeting Agenda 9 October 2026 <span>(PDF File, 21.8 MB)</span></a></h3></div></div></li>
<li class="generic-list__item generic-list__file"><div class="generic-list__header"><div class="generic-list__right"><h3 class="generic-list__title">
<a href="https://www.whyalla.sa.gov.au/__data/assets/pdf_file/0024/2055453/0-audit-committee-Workshop-agenda.pdf">Audit and Risk Committee Joint Workshop Agenda 8 October 2026 <span>(PDF File, 271.1 KB)</span></a></h3></div></div></li>
<li class="generic-list__item generic-list__file"><div class="generic-list__header"><div class="generic-list__right"><h3 class="generic-list__title">
<a href="https://www.whyalla.sa.gov.au/__data/assets/pdf_file/0030/892443/2021.05.03-Audit-Committee-Minutes-Final.pdf">2021.05.03- Audit Committee Minutes Final.pdf <span>(PDF File, 603.7 KB)</span></a></h3></div></div></li>
</ul></div></main></body></html>"""


def test_whyallas_audit_page_links_become_dated_audit_documents():
    documents = _audit_documents(AUDIT_HTML)
    assert [(d.asset_id, d.title, d.committee, d.date) for d in documents] == [
        (
            "2055458",
            "Audit and Risk Committee Meeting Agenda 9 October 2026",
            AUDIT_COMMITTEE,
            "2026-10-09",
        ),
        (
            "2055453",
            "Audit and Risk Committee Joint Workshop Agenda 8 October 2026",
            f"{AUDIT_COMMITTEE} Workshop",
            "2026-10-08",
        ),
        (
            "892443",
            "2021.05.03- Audit Committee Minutes Final.pdf",
            AUDIT_COMMITTEE,
            "2021-05-03",
        ),
    ]


def test_whyalla_fails_when_its_audit_page_lists_nothing():
    scraper = WhyallaScraper()
    scraper.years_filter = [2026]
    scraper.fetcher = PlaybackFetcher(
        [
            [
                ["selenium", scraper._page_url(scraper.listing_urls[0])],
                as_listing_page(
                    [
                        doc(
                            "1",
                            "2026-10-19",
                            "Council Meeting Agenda 19 October 2026",
                            committee="Whyalla City Council Meetings",
                        )
                    ]
                ),
            ],
            [["selenium", AUDIT_PAGE], "<html><body><main></main></body></html>"],
        ]
    )
    with pytest.raises(RuntimeError, match="audit-committee-agenda-and-minutes"):
        scraper.scraper()
