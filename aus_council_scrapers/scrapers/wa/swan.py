import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.alyka import (
    PageTypeListingScraper,
    filename_of,
    find_date,
    text_without_date,
    tidy_meeting_name,
)
from aus_council_scrapers.base import (
    ScraperReturn,
    _merge_split_meetings,
    register_scraper,
)

_BASE_URL = "https://www.swan.wa.gov.au"
_LISTING_URL = f"{_BASE_URL}/city-and-council/your-council/meetings/"

# A documented robots.txt exception. Swan's listing loads only from Alyka's
# /v1/aapi/search/htmlresult, and www.swan.wa.gov.au/robots.txt has
# `Disallow: /v1/` (checked 20 Oct 2026; the other Alyka paths 404). The
# maintainer decided on 21 Oct 2026 to read it anyway, because these papers
# are the council's official public record and its own page calls this
# endpoint for every visitor. One request a year keeps the load trivial.
# It was the first such exception. AGENTS.md lists the others; read it
# before adding another.

# Swan's fragment is an accordion, one item per meeting. The heading is the
# date and the meeting ("February 11, 2026 - Ordinary Meeting of Council"),
# typed by hand, so it also arrives as "February, 12 2020 Ordinary Meeting"
# and "October 14 ,2026 Ordinary Meeting of Council". The panel lists the
# meeting's documents by label.
#
# The year filter (`DocMeetingDateYear`) is the meeting's year, one request
# per year. Every meeting type is kept: the fetch is per year, not per
# meeting, so a type costs nothing to include. That brings in the Metro
# Outer development assessment panel, whose papers Swan publishes for the
# applications in its area.
#
# Labels are the hard part. Recent meetings say "Agenda" and "Minutes"; older
# ones say "Abridged minutes" (Swan's published minutes until 2023), "Full
# Minutes", "Agenda - Ordinary Meeting of Council October 11 2023" and
# "Metro Outer JDAP 221 - Agenda - January 5, 2023". Alongside them sit the
# agenda forum's notes, notices of meeting, attachments, "Related
# information" for the panel, reserve-account statements for the community
# advisory groups, and YouTube links.
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bmi(?:n)?utes\b", re.IGNORECASE)  # "Miutes", once
_NOT_PAPERS = re.compile(
    r"forum|notes|notice|supplementary|addendum|attachment|related|summary",
    re.IGNORECASE,
)
# The panel's headings carry a meeting number, an application address or the
# councils sharing the sitting: "MODAP 124", "MODAP139", "JDAP 221 - Lot 59
# Bushmead Road, ...", "No 124 - City of Swan - City of Gosnells". None of
# that is the meeting's name, which is the panel's.
_PANEL = re.compile(
    r"^\s*(?:(?:Metro\s+Outer\s*-?\s*)?(?:MO)?J?DAP(?=\b|\d)"
    r"|No\.?\s*\d+\s*-\s*(?:City|Shire|Town)\b)",
    re.IGNORECASE,
)
_PANEL_NAME = "Metro Outer Development Assessment Panel"
# The same bodies under the other names headings have used for them.
_RENAMED = {
    "ordinary meeting": "Ordinary Meeting of Council",
    "ordinary council meeting": "Ordinary Meeting of Council",
    "special council meeting": "Special Meeting of Council",
    "audit, risk and improvement": "Audit, Risk and Improvement Committee",
    "reconciliation action plan (rap) advisory group": (
        "Reconciliation Action Plan Advisory Group"
    ),
}


def _meeting_name(heading: str) -> str:
    name = text_without_date(heading)
    if _PANEL.match(name):
        return _PANEL_NAME
    # "Bush Fire Advisory Committee - BFAC Minutes", "Bushfire Advisory
    # Committee (BFAC)" and "BFAC Minutes - Bush Fire Advisory Committee" are
    # one committee.
    if re.search(r"\bBFAC\b|bush\s*fire advisory", name, re.IGNORECASE):
        return "Bush Fire Advisory Committee"
    name = tidy_meeting_name(name)
    name = re.sub(r"\s+Meeting$", "", name) if "Group" in name else name
    return _RENAMED.get(name.lower(), name)


@register_scraper
class SwanScraper(PageTypeListingScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("swan", "WA", _BASE_URL)

    @staticmethod
    def _documents(item) -> dict:
        found = {}
        for document in item.find_all(class_="document-item"):
            link = document.find("a", href=True)
            if not link:
                continue
            url = urllib.parse.urljoin(_BASE_URL, link["href"])
            if not filename_of(url).lower().endswith((".pdf", ".doc", ".docx")):
                continue  # YouTube
            label_element = document.find("div")
            label = (label_element or link).get_text(" ", strip=True)
            # The label decides, but some name neither type: the 19 June 2023
            # Aveley Community Advisory Group's only document is labelled
            # "19 June 2023 Aveley Community Advisory Group" and links
            # "Minutes-Aveley-Community-Advisory-Group-Meeting-...pdf". The
            # filename is the fallback then, as at Kwinana.
            if not (_MINUTES.search(label) or _AGENDA.search(label)):
                label = filename_of(url).replace("-", " ")
            if _NOT_PAPERS.search(label):
                continue
            # `setdefault`, so the first of a split agenda is the one kept.
            # "February 2, 2022 Ordinary Meeting" lists "Agenda part one" and
            # "Agenda part two"; part one is the front of the agenda, with the
            # meeting's details and order of business, which is the document
            # a reader needs to find, and the record has one agenda slot.
            if _MINUTES.search(label):
                found.setdefault("minutes", url)
            elif _AGENDA.search(label):
                found.setdefault("agenda", url)
        return found

    def _meetings(self, fragment: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(fragment, "html.parser")
        items = soup.find_all(class_="accordion-item")
        self._warn_if_full(len(items), "a year")

        results = []
        for item in items:
            button = item.find(class_="accordion-button")
            heading = button.get_text(" ", strip=True) if button else ""
            if "cancelled" in heading.lower():
                # Listed with the agenda it would have had.
                continue
            # Some 2022 panel headings give only the application ("JDAP 198 -
            # Lot 8336 (151) and Lot 7385 The Promenade, Ellenbrook"); the
            # documents' own labels carry the date.
            found = find_date(heading) or find_date(
                " ".join(
                    d.get_text(" ", strip=True)
                    for d in item.find_all(class_="document-item")
                )
            )
            if not found:
                self.logger.info(f"{self.council_name}: no date for {heading!r}")
                continue

            documents = self._documents(item)
            meeting = self._meeting(
                name=_meeting_name(heading),
                date=found[0],
                webpage_url=_LISTING_URL,
                agenda_url=documents.get("agenda"),
                minutes_url=documents.get("minutes"),
            )
            if meeting:
                results.append(meeting)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        config = self._listing_config(self._listing_page())
        offered = {
            int(v)
            for v in self.checkbox_values(config, "DocMeetingDateYear")
            if v.isdigit()
        }
        wanted = self._wanted_years()
        if offered:
            years = sorted(wanted & offered, reverse=True)
        else:
            self.logger.warning(
                f"{self.council_name}: could not read the year filter; "
                f"asking for every wanted year"
            )
            years = sorted(wanted, reverse=True)

        results = []
        for _, fragment in self._each_year(
            years,
            lambda year: self._search(config, {"DocMeetingDateYear": [str(year)]}),
        ):
            results.extend(
                m for m in self._meetings(fragment) if m.cleaned_date.year in wanted
            )

        # A meeting is sometimes listed twice, once per document.
        results = _merge_split_meetings(results)
        self._log_result(results, f"years {years}")
        return results
