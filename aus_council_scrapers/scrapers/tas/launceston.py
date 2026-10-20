"""City of Launceston—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting back to 2013, and its
year filter is exact: the per-year counts add up to the unfiltered listing's
350 results (checked 20 October 2026). The listing honours ``(pagesize=N)``,
so a year is one listing request; 2017, the busiest year, has 41 rows.

The renderer payload has taken two shapes:

* **From about mid-2025**, papers sit under ``div.meeting-document`` headings,
  each with one "Download PDF" link. The heading names the body before the
  paper—"Council Agenda - 1 October 2026", "Council Minutes - 1 October
  2026", "Special Council Meeting Agenda - 8 January 2026", "Special Meeting
  Minutes - 23 December 2025"—and heading mode anchors "Agenda" and "Minutes"
  at the start, so that leading body name is stripped first
  (`_BODY_PREFIX`). What is left of "Council Agenda Attachments - …" is an
  attachment book, and "Late Item Agenda - Special Council Meeting - …" never
  starts with the body name, so neither is taken for the agenda.
* **Before that**, the payload has no headings, only a "Related Information"
  list labelled by filename—"Council-Agenda-10-December-2020.pdf",
  "Council-Minutes-10-December-2020.pdf"—beside every item attachment of the
  meeting ("Council-Agenda-Agenda-Item-18.4-Attachment-1-Overview-Map-…").
  Heading mode reads such a payload by link text. Attachments are already
  passed over there; one item's own report ("…-Agenda-Item-16.1-…") is
  dropped here as well (`_ITEM_FILE`), since a filename joins words with
  hyphens and the base class's item rule looks for a space. Two meetings'
  only agenda is labelled as an agenda with attachments, and one meeting
  lists both plain and confirmed minutes; `_by_filename` handles both.

Two one-off defects are handled in `papers` as well. The 19 February 2026
minutes are not their section's own download link but sit in a "Related
Information" list nested inside the "Council Minutes" section, which heading
mode passes over; where a section has no download link of its own, its
nested list is read as its paper. And the 25 August 2022 minutes are
labelled "Council-Mintutes-25-August-2022.pdf", so that misspelling is read
as "Minutes". (The 11 July 2024 minutes are labelled "…-11-June-2024.pdf",
but the file is the 11 July 2024 minutes; labels are not used for dates.)

Meeting types are Ordinary Meeting (fortnightly, about 24 a year), Special
Meeting, the Amendment to Sealed Plan Hearing Committee (a planning hearing,
two meetings in 2022) and an Annual General Meeting. The AGM is the electors'
meeting on the annual report, not a meeting where Council decides anything,
so it is left out to save a payload request (`meeting_types`). One
production year is still about 23 requests—the listing and one payload per
meeting—because the ordinary meetings alone are 20 to 24 a year.

The listing's upcoming rows have no papers until the agenda is out, and are
skipped until then. robots.txt disallows only particular retired sub-pages of
``/Agendas-and-Minutes/``, none of which this fetches. The site is behind
Akamai (``Server-Timing: ak_p``), which served the identifying User-Agent
without a challenge from a home IP; it has not been measured from a GitHub
runner.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    OpenCitiesMeetingsScraper,
    _AGENDA,
    _MINUTES,
    _NOT_THE_PAPER,
    _is_pdf,
    _label,
    _papers,
)
from aus_council_scrapers.opencities_nested import nested_papers, with_loose

# The body named in front of a paper's heading, which heading mode would
# otherwise read as not being the agenda or minutes at all.
_BODY_PREFIX = re.compile(
    r"^\s*(?:special\s+)?(?:council\s+)?(?:meeting\s+)?(?=(?:agenda|minutes)\b)",
    re.IGNORECASE,
)

# One agenda item's file in the Related Information list:
# "Council-Meeting-Agenda-Item-16.1-Attachment-1-…",
# "Council-Agenda-Agenda-Item-18.4-…".
_ITEM_FILE = re.compile(r"\bitem[\s_-]*\d", re.IGNORECASE)

_MISSPELT_MINUTES = re.compile(r"\bmintutes\b", re.IGNORECASE)

# Read only where a payload has no headings; see `_by_filename`.
# "Council-Agenda-with-Attachments-2-May-2024.pdf",
# "Council-Agenda-Attachments-14-December-2023.pdf".
_AGENDA_BOOK = re.compile(r"\bagenda\s+(with\s+)?attachments\b", re.IGNORECASE)
# "Confirmed-Council-Minutes-21-August-2025.pdf"; ``\b`` keeps "Unconfirmed"
# out.
_CONFIRMED = re.compile(r"\bconfirmed\b", re.IGNORECASE)

# Ordinary and special meetings of Council, and the sealed-plan hearings
# (a planning body). Not the Annual General Meeting; see the module docstring.
_COUNCIL_AND_PLANNING = re.compile(
    r"^(?:Ordinary|Special) Meeting$|Sealed Plan", re.IGNORECASE
)


def _filename_label(anchor) -> str:
    return _label(anchor.get_text(" ", strip=True).replace("-", " "))


def _by_filename(content: BeautifulSoup, papers: dict[str, str], base_url: str):
    """Two corrections to link-text mode, for the pre-2025 payloads.

    The base class passes over any label naming attachments, since elsewhere
    that is an attachment book beside the agenda. Here two meetings publish
    no other agenda: 2 May 2024 has only "Council-Agenda-with-Attachments-…"
    (37 pages) and 14 December 2023 only "Council-Agenda-Attachments-…" (397
    pages), and both open with the agenda's notice of meeting and order of
    business (checked 20 October 2026). So where no agenda was found, such a
    book is the agenda, a "with attachments" one first. Meetings that do have
    a plain agenda keep it, so an attachment book beside one (21 August 2025)
    is never taken.

    The base class also ranks "Council-Minutes-…" and "Confirmed-Council-
    Minutes-…" equally and takes the first listed. On 21 August 2025 both are
    posted; the confirmed copy is the one adopted at the next meeting, so it
    wins.
    """
    agenda, minutes = papers.get("agenda"), papers.get("minutes")
    anchors = [
        a
        for a in content.select("div.meeting-attachments a[href]")
        if _is_pdf(a["href"].strip())
    ]
    if not agenda:
        books = [
            (not match.group(1), i, a)
            for i, a in enumerate(anchors)
            if (match := _AGENDA_BOOK.search(_filename_label(a)))
            and not _MINUTES.search(_filename_label(a))
        ]
        if books:
            agenda = urljoin(base_url, min(books)[2]["href"].strip())
    confirmed = next(
        (
            urljoin(base_url, a["href"].strip())
            for a in anchors
            if _CONFIRMED.search(label := _filename_label(a))
            and _MINUTES.search(label)
            and not _AGENDA.search(label)
            and not _NOT_THE_PAPER.search(label)
        ),
        None,
    )
    return _papers(agenda, confirmed or minutes)


@register_scraper
class LauncestonScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 43-46 s
    # (23 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 46

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True
    meeting_types = _COUNCIL_AND_PLANNING

    def __init__(self):
        super().__init__(
            "launceston",
            "TAS",
            "https://www.launceston.tas.gov.au/Agendas-and-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        # A copy, because the rules below remove and rename links, and the
        # base class counts the payload's own PDFs afterwards to warn about a
        # meeting whose every paper was rejected.
        content = BeautifulSoup(str(content), "html.parser")
        for anchor in content.select("div.meeting-attachments a[href]"):
            text = anchor.get_text(" ", strip=True)
            if _ITEM_FILE.search(text):
                anchor.decompose()
            elif _MISSPELT_MINUTES.search(text):
                anchor.string = _MISSPELT_MINUTES.sub("Minutes", text)
        for heading in content.select("div.meeting-document > h3"):
            text = heading.get_text(" ", strip=True)
            stripped = _BODY_PREFIX.sub("", text, count=1)
            if stripped != text:
                heading.string = stripped
        loose = nested_papers(content)
        papers = with_loose(super().papers(content), loose, self.base_url)
        if not content.find("div", class_="meeting-document"):
            papers = _by_filename(content, papers, self.base_url)
        return papers
