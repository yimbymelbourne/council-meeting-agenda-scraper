"""Tests for Darebin's one-file-two-labels case.

Darebin's pages sometimes link a single PDF twice, once labelled Agenda and
once Minutes. One file cannot be both, and recording it as an agenda sends
readers to a document that is not the agenda.
"""

from aus_council_scrapers.base import SCRAPER_REGISTRY
import aus_council_scrapers.scrapers  # noqa: F401

SCRAPER = next(
    s for s in SCRAPER_REGISTRY.values() if s.council_name == "darebin"
)
KEY = ("14 November 2022", "Special Council Meeting")

MINUTES = "https://x.test/docs/14november2022-specialcouncilmeetingminutes.pdf"
AGENDA = "https://x.test/docs/14november2022-specialcouncilmeetingagenda.pdf"
UNCLEAR = "https://x.test/docs/14november2022-specialcouncilmeeting.pdf"


def test_a_file_named_minutes_is_only_the_minutes():
    agenda, minutes = SCRAPER._resolve_shared_document(MINUTES, MINUTES, KEY)
    assert agenda is None
    assert minutes == MINUTES


def test_a_file_named_agenda_is_only_the_agenda():
    agenda, minutes = SCRAPER._resolve_shared_document(AGENDA, AGENDA, KEY)
    assert agenda == AGENDA
    assert minutes is None


def test_distinct_documents_are_left_alone():
    agenda, minutes = SCRAPER._resolve_shared_document(AGENDA, MINUTES, KEY)
    assert (agenda, minutes) == (AGENDA, MINUTES)


def test_a_meeting_with_only_one_document_is_untouched():
    assert SCRAPER._resolve_shared_document(None, MINUTES, KEY) == (None, MINUTES)
    assert SCRAPER._resolve_shared_document(AGENDA, None, KEY) == (AGENDA, None)


def test_an_unnameable_duplicate_is_kept_rather_than_guessed(caplog):
    """With nothing to go on, dropping a real document would be worse than
    leaving the pair as the council published it — but say so."""
    agenda, minutes = SCRAPER._resolve_shared_document(UNCLEAR, UNCLEAR, KEY)
    assert (agenda, minutes) == (UNCLEAR, UNCLEAR)
    assert "settles nothing" in caplog.text
