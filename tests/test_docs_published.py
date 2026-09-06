"""Tests for the DocAssembler blob-name reconciliation.

The cassettes prove the scrapers work end to end, but they cannot say *why*
this step exists, and a fixture diff would not distinguish a rescued filename
from a lucky one. DocAssembler's API sometimes reports a path that is not the
path it wrote: the blob has a run of spaces where the API reports a single
one. Azure matches blob names byte for byte, so those URLs 404 forever — ten
of Northern Beaches' 269 documents, and no encoding change fixes them because
both API endpoints report the same collapsed name.
"""

import urllib.parse

from aus_council_scrapers.base import DocsPublishedScraper

STORAGE = {
    "base": "https://hsdocssuite.blob.core.windows.net",
    "container": "docassembler-web-publishing",
    "sas": "?sv=2023-01-03&sr=c&sig=SIGNATURE%3D",
}
TENANT = "f7d3b1b9-0538-4bef-8d13-3b55bb00e04a"
FOLDER = "80c549cf-97e8-49b9-8334-b8366582cbb2"

# What the API reports, and what is actually in the container.
REPORTED = "Agenda - Open - Extraordinary Council Meeting - 20170906.pdf"
STORED = "Agenda - Open - Extraordinary  Council Meeting - 20170906.pdf"


class _Scraper(DocsPublishedScraper):
    publishing_slug = "northernbeaches"

    def __init__(self):
        super().__init__("test_council", "NSW")


def resolve(stored, file_path=REPORTED, folder=FOLDER):
    return _Scraper()._document_url(STORAGE, TENANT, stored, folder, file_path)


def blob_name(url):
    """The blob path back out of a composed URL."""
    prefix = f"{STORAGE['base']}/{STORAGE['container']}/"
    assert url.startswith(prefix), url
    return urllib.parse.unquote(url[len(prefix) :].split("?")[0])


def test_composes_the_blob_url_when_the_api_name_is_right():
    url = resolve({FOLDER: [REPORTED]})
    assert blob_name(url) == f"{TENANT}/{FOLDER}/{REPORTED}"
    assert url.endswith(STORAGE["sas"])


def test_uses_the_stored_name_when_the_api_collapsed_its_whitespace():
    """The whole point: the API's name 404s, the container's does not."""
    assert blob_name(resolve({FOLDER: [STORED]})) == f"{TENANT}/{FOLDER}/{STORED}"


def test_preserves_runs_of_spaces_through_encoding():
    """A single %20 where the blob has two is the failure being fixed."""
    assert "%20%20" in resolve({FOLDER: [STORED]})


def test_drops_documents_that_were_never_uploaded():
    """Two of Parramatta's 1,422 documents are listed but not stored. A URL
    known to 404 is worse than no URL at all."""
    assert resolve({FOLDER: []}) is None
    assert resolve({}) is None


def test_drops_ambiguous_matches():
    """Nothing distinguishes the candidates, so guessing would be a coin toss."""
    other = "Agenda - Open -  Extraordinary Council Meeting - 20170906.pdf"
    assert resolve({FOLDER: [STORED, other]}) is None


def test_falls_back_to_the_api_name_when_the_listing_is_unavailable():
    """A listing failure should cost the misnamed documents, not the council."""
    assert blob_name(resolve(None)) == f"{TENANT}/{FOLDER}/{REPORTED}"


def test_ignores_documents_with_no_folder_or_filename():
    assert resolve({FOLDER: [REPORTED]}, file_path=None) is None
    assert resolve({FOLDER: [REPORTED]}, folder=None) is None


def test_viewer_urls_are_never_emitted_as_documents():
    """`/document/<uuid>` is the Angular shell, not the PDF. It stays on
    `webpage_url`, where it also preserves the id the blob URL can be
    re-resolved from once the SAS token rotates."""
    assert _Scraper().base_url == "https://docspublished.com.au/northernbeaches"
    assert "docspublished.com.au" not in resolve({FOLDER: [STORED]})
