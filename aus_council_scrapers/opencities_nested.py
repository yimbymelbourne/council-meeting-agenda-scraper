"""OpenCities papers filed in a "Related Information" list instead of under
their own heading.

Heading mode (`papers_by_heading`) reads only a section's own "Download PDF"
link, and passes over the ``div.meeting-attachments`` lists, because at
Kingston those lists link other meetings' papers. Some councils that otherwise
file by heading put a paper in such a list now and then:

* Launceston's 19 February 2026 minutes and Western Downs' 19 February 2026
  agenda sit in a list nested inside their own "Minutes" or "Agenda" section,
  which has no download link of its own.
* Western Downs' 9 April 2024 agenda is in the payload's top-level list,
  beside a "Minutes" section that holds only the minutes.

These helpers are council-neutral and belong in `opencities.py`; they live
here only because that module was not open to edit when they were written.
"""

import re

from bs4 import BeautifulSoup

from aus_council_scrapers.opencities import (
    _NOT_THE_PAPER,
    _is_pdf,
    _papers,
    papers_by_link_text,
)

# A heading that is the agenda or the minutes, once any body name in front of
# it is gone.
_PAPER_HEADING = re.compile(
    r"^(?:(?:final|open|public|(?:un)?confirmed|draft)\s+)?(?:agenda|minutes)\b",
    re.IGNORECASE,
)


def nested_papers(content: BeautifulSoup) -> list:
    """Take the files of an agenda or minutes section that has no download
    link of its own, only a nested "Related Information" list.

    One file in that list is the section's paper, so the list is unwrapped
    for heading mode to read. Several files are lifted out and returned, to
    be read by their own labels (`with_loose`), since heading mode would
    otherwise take whichever is listed first.

    The payload's own Related Information list, beside the sections, is
    returned too. Heading mode ignores it wherever there are sections; here
    it is read only for a paper no section supplied.

    Edits ``content`` in place, so pass a copy where the original is still
    needed.
    """
    loose = []
    if content.find("div", class_="meeting-document"):
        for div in content.find_all("div", class_="meeting-attachments"):
            if not div.find_parent("div", class_="meeting-document"):
                loose.append(div.extract())
    for section in content.find_all("div", class_="meeting-document"):
        heading = section.find("h3")
        title = heading.get_text(" ", strip=True) if heading else ""
        if not _PAPER_HEADING.match(title) or _NOT_THE_PAPER.search(title):
            continue
        if any(
            _is_pdf(a["href"].strip())
            and not a.find_parent("div", class_="meeting-attachments")
            for a in section.find_all("a", href=True)
        ):
            continue
        nested = section.find_all("div", class_="meeting-attachments")
        pdfs = [
            a
            for div in nested
            for a in div.find_all("a", href=True)
            if _is_pdf(a["href"].strip())
        ]
        for div in nested:
            if len(pdfs) == 1:
                div.unwrap()
            else:
                loose.append(div.extract())
    return loose


def with_loose(papers: dict[str, str], loose: list, base_url: str) -> dict[str, str]:
    """Fill a paper heading mode did not find from the lifted-out files."""
    if not loose:
        return papers
    extra = papers_by_link_text(
        BeautifulSoup("".join(str(div) for div in loose), "html.parser"), base_url
    )
    return _papers(
        papers.get("agenda") or extra.get("agenda"),
        papers.get("minutes") or extra.get("minutes"),
    )
