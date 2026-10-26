"""Benalla's dating and misfiled-paper rules, pinned through `scraper()`.

The recorded page has a year on every current-cycle heading and only one
misfiled paper, so a re-record would not notice these rules breaking. Each
test builds a small page in the same markup and checks what comes out.
"""

from aus_council_scrapers import clock
from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.vic.benalla import BenallaScraper

_UPLOADS = "https://www.benalla.vic.gov.au/wp-content/uploads/2026/10"


def _block(heading: str, *rows: tuple[str, str]) -> str:
    body = "".join(
        f"""
        <div class="rounded-8">
          <div><span class="text-14 font-semibold">{label}</span></div>
          <div><a href="{_UPLOADS}/{file}">Download</a></div>
        </div>"""
        for label, file in rows
    )
    return f"""
    <div class="nn-block-download">
      <h4 class="mb-0">{heading}</h4>
      <div>{body}</div>
    </div>"""


def _page(current: str, sections: dict[str, list[str]]) -> str:
    html = ["<h2>Current meeting cycle</h2>", current]
    for title, blocks in sections.items():
        html.append(f"<h3>{title}</h3>")
        html.extend(blocks)
    return f"<html><body>{''.join(html)}</body></html>"


class _OnePage(Fetcher):
    def __init__(self, html: str):
        self.html = html

    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        return self.html

    def get_selenium_driver(self):
        raise AssertionError("Benalla is plain HTML")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("Benalla is plain HTML")


def _run(html: str, years: list[int]) -> dict[str, tuple]:
    scraper = BenallaScraper()
    scraper.fetcher = _OnePage(html)
    scraper.years_filter = years
    return {r.date: (r.name, r.agenda_url, r.minutes_url) for r in scraper.scraper()}


_PAST = {
    "Council Meetings 2026": [
        _block(
            "14 October 2026 – Council Meeting",
            ("Agenda", "Agenda-Council-Meeting-14-October-2026.pdf"),
        )
    ]
}


def test_a_year_less_current_meeting_takes_its_year_from_a_file_name():
    # Late December: the next meeting is in the new year.
    current = _block(
        "3 February – Council Meeting",
        ("Agenda", "Agenda-Council-Meeting-3-February-2027.pdf"),
    )
    with clock.frozen("2026-12-20"):
        out = _run(_page(current, _PAST), [2026, 2027])
    assert out["2027-02-03"][1].endswith("3-February-2027.pdf")


def test_a_year_less_current_meeting_without_a_dated_file_is_nearest_today():
    current = _block(
        "28 October – Additional Council Meeting",
        ("Agenda", "Agenda-Additional-Council-Meeting.pdf"),
    )
    with clock.frozen("2026-10-26"):
        out = _run(_page(current, _PAST), [2025, 2026, 2027])
    assert "2026-10-28" in out
    assert "2025-10-28" not in out and "2027-10-28" not in out


def test_a_paper_naming_a_date_with_no_meeting_stays_in_its_block():
    # The meeting moved from 9 to 16 September but its minutes kept the old
    # date; no meeting is listed on 9 September.
    sections = {
        "Council Meetings 2026": [
            _block(
                "16 September 2026 – Council Meeting",
                ("Agenda", "Agenda-Council-Meeting-16-September-2026.pdf"),
                ("Minutes", "Minutes-Council-Meeting-9-September-2026.pdf"),
            )
        ]
    }
    current = _block(
        "28 October 2026 – Council Meeting",
        ("Agenda", "Agenda-Council-Meeting-28-October-2026.pdf"),
    )
    with clock.frozen("2026-10-26"):
        out = _run(_page(current, sections), [2026])
    assert out["2026-09-16"][2].endswith("Minutes-Council-Meeting-9-September-2026.pdf")


def test_a_misfiled_paper_moves_to_the_meeting_its_file_names():
    # As on the live page: the 15 Oct 2025 committee block links the 21 Oct
    # 2025 Additional Council Meeting agenda, whose own row has no link.
    sections = {
        "Council Meetings 2025": [
            _block(
                "21 October 2025 – Additional Council Meeting",
                ("Minutes", "Minutes-Additional-Council-Meeting-21-October-2025.pdf"),
            )
        ],
        "Finance and Planning Committee Meetings 2025": [
            _block(
                "15 October 2025 – Additional Finance and Planning Committee Meeting",
                ("Agenda", "Agenda-Additional-Council-Meeting-21-October-2025-1.pdf"),
                ("Minutes", "Minutes-Finance-and-Planning-15-October-2025.pdf"),
            )
        ],
    }
    current = _block(
        "28 October 2026 – Council Meeting",
        ("Agenda", "Agenda-Council-Meeting-28-October-2026.pdf"),
    )
    with clock.frozen("2026-10-26"):
        out = _run(_page(current, sections), [2025])
    assert out["2025-10-21"][1].endswith("21-October-2025-1.pdf")
    assert out["2025-10-15"][1] is None
