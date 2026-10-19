"""Western Downs Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting from 2020; its year
filter also offers 2018, which is empty. The per-year counts add up to the
unfiltered listing's 103 results (checked 20 October 2026), and a year fits
on one listing request with ``(pagesize=N)``.

Papers are filed under headings carrying the date—"Agenda 15 October 2026",
"Minutes 9 December" (sic)—with every link labelled "Download PDF", so
``papers_by = "heading"``. Heading mode matches the paper's name at the
start of the heading, and three kinds of heading need help first
(`papers`):

* Since 2026 some minutes headings name the body first: "Ordinary Meeting
  of Council Minutes 19 February 2026". That leading name is stripped.
* The 18 January 2024 minutes are filed under a heading that is only a
  (wrong) date, "18 January 2023". A heading naming neither paper is read by
  its file's name instead ("…-minutes-18-january-2024-confirmed.pdf").
* The 19 February 2026 agenda is not the section's own download link but
  sits in a "Related Information" list nested inside the Agenda section,
  which heading mode passes over (it holds other meetings' papers at
  Kingston). Where a section has no download link of its own, its nested
  list is read as the section's paper.

One listing row has the wrong date. The row for cvid ``62ec9ff3-…`` says 21
March 2021, but its papers are "Agenda 21 April 2021" and "Minutes 21 April
2021", and the 19 May 2021 minutes confirm "the Minutes of the Ordinary
Meeting of Council held on Wednesday, 21 April 2021". The real 17 March 2021
meeting has a row of its own. It is the only row whose papers give another
date, so it is corrected by cvid (`_DATE_FIXES`), as Gold Coast does, rather
than by trusting paper dates in general.

Meeting types are only "Ordinary Meeting of Council" and "Special Meeting",
so nothing is filtered: one production year is about 16 requests. Meetings
for the rest of the year are listed in advance with empty payloads, and are
skipped until their agenda is published.

Not the eScribe portal ``pub-wdrc.escribemeetings.com``, which holds only two
meetings from May 2019—an abandoned trial. The site is behind Akamai
(``Server-Timing: ak_p``), which served the identifying User-Agent without a
challenge from a home IP; it has not been measured from a GitHub runner.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import (
    ListingRow,
    OpenCitiesMeetingsScraper,
    _AGENDA,
    _is_minutes_file,
    _is_pdf,
    _label,
)
from aus_council_scrapers.opencities_nested import nested_papers, with_loose


# "Ordinary Meeting of Council Minutes 19 February 2026",
# "Ordinary Meeting of Council Draft Minutes 19 March 2026".
_BODY_PREFIX = re.compile(
    r"^\s*(?:ordinary|special)\s+meeting\s+of\s+council\s+", re.IGNORECASE
)
_NAMES_A_PAPER = re.compile(r"\b(?:agenda|minutes)\b", re.IGNORECASE)

# Listing rows whose date is wrong, by cvid; see the module docstring.
_DATE_FIXES = {
    "62ec9ff3-a3d6-4706-9ac8-7d74cfb41183": "21 April 2021",
}


def _file_name(href: str) -> str:
    return _label(href.rsplit("/", 1)[-1].replace("-", " "))


@register_scraper
class WesternDownsScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 30 s
    # (16 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 30

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "western_downs",
            "QLD",
            "https://www.wdrc.qld.gov.au/Council/About-WDRC/Council-Meetings",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        # A copy, because headings are renamed and lists lifted out below,
        # and the base class counts the payload's own PDFs afterwards to warn
        # about a meeting whose every paper was rejected.
        content = BeautifulSoup(str(content), "html.parser")
        for section in content.find_all("div", class_="meeting-document"):
            heading = section.find("h3")
            if heading is None:
                continue
            text = heading.get_text(" ", strip=True)
            renamed = _BODY_PREFIX.sub("", text, count=1)
            if not _NAMES_A_PAPER.search(renamed):
                first = next(
                    (
                        a["href"].strip()
                        for a in section.find_all("a", href=True)
                        if _is_pdf(a["href"].strip())
                    ),
                    None,
                )
                if first and _is_minutes_file(first):
                    renamed = "Minutes"
                elif first and _AGENDA.search(_file_name(first)):
                    renamed = "Agenda"
            if renamed != text:
                heading.string = renamed
        loose = nested_papers(content)
        return with_loose(super().papers(content), loose, self.base_url)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is not None:
            record.date = _DATE_FIXES.get(row.cvid, record.date)
        return record
