"""Date reconciliation on the Ionata meeting archives.

The card's date field, its title and its documents' filenames are typed
separately and disagree often enough (Glenorchy most of all) that the base
class votes between them, and takes a document off a card only when it names
a meeting the listing actually has. The recorded fixtures exercise this on
real cards, but a re-record would accept a regression silently — these pin
the rules themselves, through the scraper's own entry point.
"""

from aus_council_scrapers.base import Fetcher
from aus_council_scrapers.scrapers.tas.clarence import ClarenceScraper

_ASSETS = "https://assets.ccc.tas.gov.au/uploads/2023/11"


def _card(title: str, date: str, agenda: str, minutes: str) -> str:
    return f"""
    <div class="col-lg-6 content-card"><div class="content-card__inner">
      <h3 class="content-card__title">{title}</h3>
      <div class="content-card__info"><div>{date}</div><div>Council Chambers</div></div>
      <div class="content-card__buttons">
        <a class="icon-btn" href="{agenda}"><span class="icon-btn__text">Agenda</span></a>
        <a class="icon-btn" href="{minutes}"><span class="icon-btn__text">Minutes</span></a>
      </div>
    </div></div>"""


class _OnePage(Fetcher):
    """Serves one listing page for the one year asked for."""

    def __init__(self, html: str):
        self.html = html
        self.requested: list[str] = []

    def fetch_with_requests(self, url, method="GET", **kwargs) -> str:
        self.requested.append(url)
        return self.html

    def get_selenium_driver(self):
        raise AssertionError("Ionata archives are plain HTML")

    def fetch_with_selenium(self, url, wait_time=10, wait_condition=None):
        raise AssertionError("Ionata archives are plain HTML")


def _scrape(*cards: str):
    scraper = ClarenceScraper()
    scraper.fetcher = _OnePage(f"<html><body>{''.join(cards)}</body></html>")
    scraper.years_filter = [2020]
    return {r.date: r for r in scraper.scraper()}, scraper.fetcher.requested


def test_title_and_filenames_outvote_a_mistyped_date_field():
    meetings, _ = _scrape(
        _card(
            "Clarence City Council Meeting – 7 February 2020",
            "8 February 2020 - 7:00pm",
            f"{_ASSETS}/a07.02.20.pdf",
            f"{_ASSETS}/m07.02.20.pdf",
        )
    )
    assert list(meetings) == ["2020-02-07"]


def test_another_meetings_agenda_is_taken_off_the_card():
    # Clarence's 9 June 2020 card links the 29 June agenda.
    meetings, _ = _scrape(
        _card(
            "Clarence City Council Meeting – 29 June 2020",
            "29 June 2020 - 7:00pm",
            f"{_ASSETS}/a29.06.20.pdf",
            f"{_ASSETS}/m29.06.20.pdf",
        ),
        _card(
            "Clarence City Council Meeting – 9 June 2020",
            "9 June 2020 - 7:00pm",
            f"{_ASSETS}/a29.06.20.pdf",
            f"{_ASSETS}/m09.06.20.pdf",
        ),
    )
    assert meetings["2020-06-29"].agenda_url == f"{_ASSETS}/a29.06.20.pdf"
    assert meetings["2020-06-09"].agenda_url is None
    assert meetings["2020-06-09"].minutes_url == f"{_ASSETS}/m09.06.20.pdf"
    assert meetings["2020-06-09"].download_url == f"{_ASSETS}/m09.06.20.pdf"


def test_an_adjourned_meetings_agenda_stays_when_no_meeting_has_its_date():
    # 23 January 2023 resumed the adjourned 16 January meeting, under the
    # 16 January agenda; there is no 16 January card for it to belong to.
    meetings, _ = _scrape(
        _card(
            "Clarence City Council Meeting – 20 January 2020",
            "20 January 2020 - 7:00pm",
            f"{_ASSETS}/a13.01.20.pdf",
            f"{_ASSETS}/m20.01.20.pdf",
        )
    )
    assert meetings["2020-01-20"].agenda_url == f"{_ASSETS}/a13.01.20.pdf"


def test_a_viewer_link_is_not_stored_as_the_agenda():
    meetings, requested = _scrape(
        _card(
            "Clarence City Council Meeting – 13 July 2020",
            "13 July 2020 - 7:00pm",
            "https://resources.ccc.tas.gov.au/public/09f5a67187db",
            f"{_ASSETS}/m13.07.20.pdf",
        )
    )
    assert meetings["2020-07-13"].agenda_url is None
    assert meetings["2020-07-13"].minutes_url == f"{_ASSETS}/m13.07.20.pdf"
    # One year asked for, one filtered page fetched.
    assert requested == [f"{ClarenceScraper.listing_url}?f_year=2020"]


def test_a_special_meeting_filename_names_a_card_titled_as_ordinary():
    # Clarence's 10 June 2025 card is titled "Clarence City Council Meeting"
    # and links Special-Council-Meeting-Agenda-10-June-2025.pdf.
    meetings, _ = _scrape(
        _card(
            "Clarence City Council Meeting – 10 June 2020",
            "10 June 2020 - 5:00pm",
            f"{_ASSETS}/Special-Council-Meeting-Agenda-10-June-2020.pdf",
            f"{_ASSETS}/Council-Special-Meeting-Minutes-10.06.20.pdf",
        ),
        _card(
            "Clarence City Council Meeting – 15 June 2020",
            "15 June 2020 - 7:00pm",
            f"{_ASSETS}/a15.06.20.pdf",
            f"{_ASSETS}/m15.06.20.pdf",
        ),
    )
    assert meetings["2020-06-10"].name == "Special Council Meeting"
    assert meetings["2020-06-15"].name == "Council Meeting"
