"""Town of Cambridge—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds every meeting body back to 1995,
with upcoming Council meetings on it as soon as their papers are out. The
``dlv_`` year filter and pager are plain GETs, so the form postbacks the
listing's own controls use are never needed.

Papers are filed under headings, so ``papers_by = "heading"``. An "Addendum"
heading sits beside "Agenda" on some meetings (22 September 2026) and is not
the agenda; heading mode passes it by. An upcoming Ordinary Council Meeting
first appears with "public briefing papers" under its Agenda heading—the
papers for the Agenda Briefing Forum the week before, which carry the same
officer reports and recommendations—and the final agenda replaces them once
it is published. Those briefing papers are stored as the agenda, since the
council files them as one and they are what is available before the meeting.

The list also carries Audit, Policy & Legislation, Public Art and CEO
committees, electors' meetings and annual general meetings of electors. Each
listed meeting costs a payload request, so only Council meetings and the
Development Committee (a planning body, which met in 2022 and 2023) are
fetched. With that, one production year is 17 requests and 33 s (2026,
measured in October 2026).

Cambridge files papers loosely enough that three heading rules in the base
class were written against it: a minutes PDF filed under "Agenda" (8 April
2024, 20 September 2022) is not taken as the agenda; "Public Minutes" beside
"Confidential Minutes" counts as the minutes; and "Minutes without
attachments" beside "Minutes with Attachments" (25 February 2025) is the
minutes, where the second is an attachment book. Two of the council's slips
cannot be read around and are left as published: the 25 February 2020
agenda is a file named ``2019_02_25a.pdf``, and the 28 June 2022 minutes
carry the agenda's name, ``2022_06_28a.pdf``, though the file is the
minutes.

One meeting files its agenda only as a book with attachments: 20 September
2023's sole Agenda heading is "Agenda (Reports and Attachments)", a 107 MB
file, which the base class passes over as an attachment book. Its Related
Information list holds "Agenda - Reports only", the 5 MB agenda the other
meetings file under "Agenda". So when the headings give no agenda, a
Related Information link labelled "Agenda - Reports only" is taken, and
failing that an Agenda heading that says it holds the reports. Both are
narrow on purpose: Related Information here is otherwise full of "Agenda
Briefing Forum Notes" and addenda, none of which is the agenda.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    OpenCitiesMeetingsScraper,
    _is_pdf,
    _label,
)

# "Agenda - Reports only (PDF, 5MB)": the agenda without its attachments.
_REPORTS_ONLY = re.compile(r"^agenda\s*[-–—:]\s*reports\s+only\b", re.IGNORECASE)
# "Agenda (Reports and Attachments)": the agenda bound with its attachments.
_AGENDA_WITH_REPORTS = re.compile(r"^agenda\b.*\breports\b", re.IGNORECASE)


@register_scraper
class CambridgeScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 34 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 34

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    # Each year-filtered page carries the full year dropdown, so production
    # skips the bare first page.
    year_filtered_first_page = True
    # "Ordinary Council Meeting", "Special Council Meeting", "Special Council
    # Meeting (Adjourned)" and "Development Committee Meeting".
    meeting_types = re.compile(
        r"^(?:ordinary|special) council meeting\b|^development committee",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__(
            "cambridge",
            "WA",
            "https://www.cambridge.wa.gov.au/About/Town-Council/Agendas-Minutes",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers = super().papers(content)
        if "agenda" in papers:
            return papers
        agenda = self._reports_only_link(content) or self._agenda_book(content)
        if agenda and agenda != papers.get("minutes"):
            papers["agenda"] = agenda
        return papers

    def _reports_only_link(self, content: BeautifulSoup) -> str | None:
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            if _is_pdf(href) and _REPORTS_ONLY.match(
                _label(anchor.get_text(" ", strip=True))
            ):
                return urljoin(self.base_url, href)
        return None

    def _agenda_book(self, content: BeautifulSoup) -> str | None:
        for section in content.find_all("div", class_="meeting-document"):
            h3 = section.find("h3")
            if not h3 or not _AGENDA_WITH_REPORTS.match(
                _label(h3.get_text(" ", strip=True))
            ):
                continue
            # The section's own file, not one in a nested Related
            # Information list.
            formats = section.find("div", class_="alt-formats")
            anchor = formats.find("a", href=True) if formats else None
            if anchor and _is_pdf(anchor["href"].strip()):
                return urljoin(self.base_url, anchor["href"].strip())
        return None
