"""The document-list checks in `CheckedDocsPublishedScraper`.

The cassettes show what the eight councils on this base return, but a
re-record would quietly absorb a check that stopped working: Central Coast's
supplementary papers would come back as agendas and the fixture would simply
change. Each test here is one record shape seen on a live tenant on 20 Oct
2026, driven through `scraper()` so the base class's own URL building and
skipping are in the loop.
"""

import json
import urllib.parse

import requests

from aus_council_scrapers.base import DocsPublishedScraper
from aus_council_scrapers.docspublished_checked import CheckedDocsPublishedScraper
from tests.cassette import PlaybackFetcher

API = DocsPublishedScraper.API_ROOT
ORG = {"Id": "org-id", "Key": "tenant-key"}
SHELL = '<html><head><base href="/"></head><script src="main-ABC123.js"></script>'
BUNDLE = (
    'x={azureConnectionString:"https://blob.example",'
    'azureContainerName:"c",azureSasToken:"?sig=s"}'
)


class _Fetcher(PlaybackFetcher):
    """Serves the organisation, portal and document list. The blob listing
    is refused, so the base class trusts the API's filenames."""

    def __init__(self, documents):
        super().__init__([])
        self._pages = {
            f"{API}/organisation/example": json.dumps(ORG),
            "https://docspublished.com.au/example": SHELL,
            "https://docspublished.com.au/main-ABC123.js": BUNDLE,
            f"{API}/documents/org-id": json.dumps(documents),
        }

    def fetch_with_requests(self, url, method="GET", **kwargs):
        if url in self._pages:
            return self._pages[url]
        raise requests.ConnectionError(url)


class _Scraper(CheckedDocsPublishedScraper):
    publishing_slug = "example"

    def __init__(self):
        super().__init__("example", "NSW")


def record(
    date,
    agenda=None,
    minutes=None,
    meeting_type="Ordinary Council Meeting",
    supporting=(),
    agenda_size=None,
):
    """One document-list record. `date` is local (Sydney, UTC+11 in summer
    and +10 in winter); stamped at 07:00 UTC it is 5 or 6 pm the same day.
    A paper's size defaults to one derived from its name, so two uploads of
    one file match unless a test says otherwise."""
    doc = {"MeetingType": meeting_type, "MeetingDate": f"{date}T07:00:00"}
    for kind, name, size in (
        ("Agenda", agenda, agenda_size),
        ("Minutes", minutes, None),
    ):
        doc[f"{kind}DocumentId"] = f"{kind}-{name}" if name else None
        doc[f"{kind}AssembledDocFolderName"] = f"folder-{name}" if name else None
        doc[f"{kind}DocumentFilePath"] = name
        doc[f"{kind}SizeInBytes"] = (size or 1000 * len(name)) if name else None
    doc["SupportingDocuments"] = [
        {
            "DocumentId": f"s-{name}",
            "AssembledDocFolderName": f"folder-{name}",
            "DocumentFilePath": name,
            "Title": title,
            "SizeInBytes": 1000 * len(name),
            "WP_DocumentType": {"Name": kind},
        }
        for name, title, kind in supporting
    ]
    return doc


def scrape(*documents):
    scraper = _Scraper()
    scraper.fetcher = _Fetcher(list(documents))
    return {
        m.date: (_file(m.agenda_url), _file(m.minutes_url)) for m in scraper.scraper()
    }


def _file(url):
    if not url:
        return None
    return urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])


def test_a_supplementary_paper_gives_way_to_the_agenda_among_the_supporting_documents():
    """Central Coast, 8 February 2021: the agenda slot held the
    Supplementary Attachments Paper and the business paper was a supporting
    document. The supplementary paper filed as its own "Agenda" type is not
    taken either."""
    meetings = scrape(
        record(
            "2021-02-08",
            agenda="Ordinary Council 08022021 Agenda Attachment SUP.pdf",
            minutes="Ordinary Council 08022021 Minutes.pdf",
            supporting=[
                (
                    "Ordinary Council 08022021 Attachment EXCLUDED.pdf",
                    "Attachment",
                    "Attachments",
                ),
                (
                    "Ordinary Council 08022021 Agenda SUP.pdf",
                    "Agenda Supplementary",
                    "Agenda",
                ),
                (
                    "Ordinary Council 08022021 Agenda Attachment.pdf",
                    "Ordinary Council Agenda",
                    "Agenda",
                ),
            ],
        )
    )
    assert meetings["2021-02-08"] == (
        "Ordinary Council 08022021 Agenda Attachment.pdf",
        "Ordinary Council 08022021 Minutes.pdf",
    )


def test_a_supplementary_paper_with_no_agenda_to_replace_it_is_dropped():
    meetings = scrape(
        record(
            "2022-10-11",
            agenda="Ordinary Council 11102022 Agenda Attachment SUP.pdf",
            minutes="Ordinary Council 11102022 Minutes.pdf",
        ),
        record(
            "2023-10-26",
            agenda="Ordinary Council Meeting - 26 October 2023 - Finance Report.pdf",
        ),
    )
    assert meetings == {"2022-10-11": (None, "Ordinary Council 11102022 Minutes.pdf")}


def test_minutes_in_the_agenda_slot_fill_an_empty_minutes_slot_and_are_dropped_otherwise():
    """West Daly, 27 March 2025, had only minutes, uploaded as the agenda.
    Albury's 13 April 2026 committee had its own minutes and another
    meeting's in the agenda slot."""
    meetings = scrape(
        record(
            "2025-03-27",
            agenda="Ordinary Council Meeting - 27 March 2025 - Minutes.pdf",
        ),
        record(
            "2026-04-13",
            agenda="Committee - 13 April 2026 - Minutes (1).pdf",
            minutes="Committee - 13 April 2026 - Minutes.pdf",
        ),
    )
    assert meetings == {
        "2025-03-27": (None, "Ordinary Council Meeting - 27 March 2025 - Minutes.pdf"),
        "2026-04-13": (None, "Committee - 13 April 2026 - Minutes.pdf"),
    }


def test_minutes_in_the_agenda_slot_give_way_to_a_supporting_agenda():
    """West Daly, 25 January 2024: the agenda slot held a second copy of the
    minutes, and the agenda itself was a supporting document typed "Agenda"
    whose filename names no paper type."""
    meetings = scrape(
        record(
            "2024-01-25",
            agenda="Ordinary Council Meeting - 25 January 2024 - Minutes (1).pdf",
            supporting=[
                (
                    "Ordinary Council Meeting - 25 January 2024.pdf",
                    "Ordinary Council Meeting - 25 January 2024",
                    "Agenda",
                ),
            ],
        )
    )
    assert meetings["2024-01-25"] == (
        "Ordinary Council Meeting - 25 January 2024.pdf",
        "Ordinary Council Meeting - 25 January 2024 - Minutes (1).pdf",
    )


def test_minutes_among_the_supporting_documents_fill_an_empty_minutes_slot():
    """Groote, 29 September 2025: the minutes were attached as a supporting
    document typed "Agenda". The previous meeting's minutes, attached for
    confirmation, name another day and are not taken."""
    meetings = scrape(
        record(
            "2025-09-29",
            agenda="Meeting of Council Open - 29 September 2025.pdf",
            supporting=[
                (
                    "Meeting of Council Open - 25 August 2025 - Minutes.pdf",
                    "Previous minutes",
                    "Minutes",
                ),
                (
                    "Meeting of Council Open - 29 September 2025 - Minutes.pdf",
                    "Minutes",
                    "Agenda",
                ),
            ],
        ),
        record(
            "2025-10-27",
            agenda="Meeting of Council Open - 27 October 2025.pdf",
            supporting=[
                (
                    "Meeting of Council Open - 29 September 2025 - Minutes.pdf",
                    "Previous minutes",
                    "Minutes",
                ),
            ],
        ),
    )
    assert meetings == {
        "2025-09-29": (
            "Meeting of Council Open - 29 September 2025.pdf",
            "Meeting of Council Open - 29 September 2025 - Minutes.pdf",
        ),
        "2025-10-27": ("Meeting of Council Open - 27 October 2025.pdf", None),
    }


def test_unconfirmed_minutes_give_way_to_confirmed_ones():
    """West Daly, 26 June 2025: the slot held the unconfirmed minutes, and
    the confirmed minutes were attached beside them."""
    meetings = scrape(
        record(
            "2025-06-26",
            agenda="Ordinary Council Meeting - 26 June 2025.pdf",
            minutes="Ordinary Council Meeting - 26 June 2025 - Minutes_unconfirmed.pdf",
            supporting=[
                (
                    "Ordinary Council Meeting - 26 June 2025 - Minutes.pdf",
                    "Minutes",
                    "Minutes",
                ),
            ],
        )
    )
    assert meetings["2025-06-26"] == (
        "Ordinary Council Meeting - 26 June 2025.pdf",
        "Ordinary Council Meeting - 26 June 2025 - Minutes.pdf",
    )


def test_a_paper_naming_another_records_day_moves_to_that_record():
    """Central Coast's 11 February 2022 record held the 11 October agenda,
    whose own record had only minutes; the 11 February record is then empty
    and skipped. Its 9 March 2021 record held a copy of the 9 November
    agenda (same name, same size), whose record already had it, so it is
    only dropped."""
    meetings = scrape(
        record("2022-02-11", agenda="Ordinary Council 11102022 Agenda.pdf"),
        record("2022-10-11", minutes="Ordinary Council 11102022 Minutes.pdf"),
        record(
            "2021-03-09",
            agenda="Ordinary Council 09112021 Agenda.pdf",
            minutes="Ordinary Council 09032021 Minutes.pdf",
        ),
        record("2021-11-09", agenda="Ordinary Council 09112021 Agenda.pdf"),
    )
    assert meetings == {
        "2022-10-11": (
            "Ordinary Council 11102022 Agenda.pdf",
            "Ordinary Council 11102022 Minutes.pdf",
        ),
        "2021-03-09": (None, "Ordinary Council 09032021 Minutes.pdf"),
        "2021-11-09": ("Ordinary Council 09112021 Agenda.pdf", None),
    }


def test_a_paper_naming_a_day_whose_record_holds_a_different_paper_stays():
    """Only a copy of the other record's file is dropped. A different file
    under the other day's name may be this meeting's agenda with a filename
    copied from another meeting, and dropping it would lose that agenda."""
    meetings = scrape(
        record(
            "2021-03-09",
            agenda="Ordinary Council 09112021 Agenda.pdf",
            agenda_size=111,
        ),
        record(
            "2021-11-09",
            agenda="Ordinary Council 09112021 Agenda.pdf",
            agenda_size=222,
        ),
    )
    assert meetings == {
        "2021-03-09": ("Ordinary Council 09112021 Agenda.pdf", None),
        "2021-11-09": ("Ordinary Council 09112021 Agenda.pdf", None),
    }


def test_a_filename_date_with_no_record_on_that_day_is_not_believed():
    """Pormpuraaw's 20 October 2026 agenda is filed as "19 October 2026";
    the notice inside says the 20th. Only another record of the same type
    on the named day is evidence the paper is misfiled."""
    meetings = scrape(
        record("2026-10-20", agenda="Ordinary Council Meeting -19 October 2026.pdf"),
        record(
            "2026-10-19",
            agenda="Planning Panel - 19 October 2026.pdf",
            meeting_type="Planning Panel",
        ),
    )
    assert meetings["2026-10-20"] == (
        "Ordinary Council Meeting -19 October 2026.pdf",
        None,
    )


def test_an_agenda_only_and_a_minutes_only_record_of_one_meeting_are_joined():
    meetings = scrape(
        record(
            "2019-06-11",
            agenda="Notice of Community Forum - Tuesday 11 June 2019.pdf",
            meeting_type="Community Forum",
        ),
        record(
            "2019-06-11",
            minutes="Record of Proceedings - Tuesday 11 June 2019.pdf",
            meeting_type="Community Forum",
        ),
    )
    assert meetings == {
        "2019-06-11": (
            "Notice of Community Forum - Tuesday 11 June 2019.pdf",
            "Record of Proceedings - Tuesday 11 June 2019.pdf",
        )
    }
