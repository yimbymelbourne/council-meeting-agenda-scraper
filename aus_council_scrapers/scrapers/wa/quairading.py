import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_LISTING_URL = (
    "https://www.quairading.wa.gov.au/my-council/committee-meetings/council-minutes/"
)

# Every paper Quairading has put online since 2019 is on this one page, in
# server-rendered tabs: one tab per body and paper kind ("COUNCIL MEETING
# AGENDA", "COUNCIL MEETING MINUTES", "AUDIT AND RISK MEETING AGENDA", ...),
# each a list of single-link cards. One request covers the whole history, so
# every body is read; there is nothing to save by leaving committees out.
#
# A card's label is hand-typed ("ORDINARY COUNCIL MEETIN AGENDA 30 APRIL
# 2026", "SPECIAL COUNCIL MEETING MINTUES 23 OCTOBER 2023"), so the body and
# the kind of paper come from the tab, which is consistent, and only the date
# and the ordinary/special distinction come from the label.

# Canonical names per tab body, so that an agenda and its minutes pair up
# even when one card says "AUDIT, RISK & IMPROVEMENT" and the other "AUDIT,
# RISK AND IMPROVEMENT".
_BODY_NAMES = {
    "COUNCIL MEETING": "Council Meeting",
    "AUDIT AND RISK MEETING": "Audit and Risk Committee Meeting",
    "RECONCILIATION ACT PLAN MEETING": "Reconciliation Action Plan Committee Meeting",
    "BUSH FIRE ADVISORY COMMITTEE": "Bush Fire Advisory Committee Meeting",
    "LOCAL EMERGENCY MANAGEMENT COMMITTEE": "Local Emergency Management Committee Meeting",
    "ANNUAL ELECTORS MEETING": "Annual Electors Meeting",
}

_TAB = re.compile(r"^(?P<body>.+?)\s+(?P<kind>AGENDA|MINUTES)$", re.IGNORECASE)

_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
    re.IGNORECASE,
)
# "24 APRIL-3 MAY 2023": a span, not a meeting date. Neither end can be
# assumed to be the meeting, so the card is left out.
_DATE_SPAN = re.compile(
    r"\d{1,2}\s+[A-Za-z]+\s*[-–]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}", re.IGNORECASE
)
_ISO_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")

# Late items and the second part of a split agenda are extra papers for a
# meeting whose main agenda is its own card.
_NOT_THE_PAPER = re.compile(r"\blate\b|\bpart[\s-]*2\b", re.IGNORECASE)
_UNCONFIRMED = re.compile(r"\bunconfirmed\b", re.IGNORECASE)

# Cards whose label (and filename) give the wrong meeting, found by reading
# the PDFs' first pages. Keyed by filename; the value is the meeting the
# paper is really for, or None to leave a paper out that belongs to no
# meeting on the page.
_MISLABELLED: dict[str, Optional[str]] = {
    # "ORDINARY COUNCIL MEETING AGENDA 17 JULY 2023" is the notice and agenda
    # for the 27 July 2023 meeting, whose minutes card is dated 27 July.
    "ORDINARY-COUNCIL-MEETING-17-JULY-2023-PUBLIC.pdf": "2023-07-27",
    # "AUDIT & RISK COMMITTEE MEETING AGENDA 7 JUNE 2023" opens "Audit & Risk
    # Committee Minutes | 7th June 2022"; the 13 June 2023 agenda is its own
    # card.
    "AUDIT-RISK-COMMITTEE-AGENDA-7-JUNE-2023.pdf": None,
}


@register_scraper
class QuairadingScraper(BaseScraper):
    def __init__(self):
        super().__init__("quairading", "WA", "https://www.quairading.wa.gov.au")

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser"
        )
        years_filter = getattr(self, "years_filter", None)

        # (name, date) -> {"agenda": [(label, url)], "minutes": [...]}, in
        # page order.
        meetings: dict[tuple[str, str], dict[str, list[tuple[str, str]]]] = {}

        for section in soup.select("div.w-tabs-section"):
            header = section.select_one(".w-tabs-section-header")
            tab = _TAB.match(header.get_text(" ", strip=True)) if header else None
            if not tab:
                # The recordings tab, whose cards are MP3s.
                continue
            body = tab.group("body").upper()
            kind = tab.group("kind").lower()

            for card in section.select("article.w-grid-item"):
                link = card.find("a", href=True)
                if not link:
                    continue
                href = link["href"].strip().replace("http://", "https://", 1)
                if not href.lower().endswith(".pdf"):
                    # A handful of 2019 and 2024 papers are Word files.
                    continue
                label = link.get_text(" ", strip=True)
                filename = href.rsplit("/", 1)[-1]
                # A few cards have no label; the filename then stands in
                # for it ("2025-02-11-Audit-Risk-Committee-Meeting-Minutes-
                # Unconfirmed.pdf").
                text = label or filename.rsplit(".", 1)[0].replace("-", " ")
                if _NOT_THE_PAPER.search(text):
                    continue
                if _DATE_SPAN.search(text):
                    self.logger.warning(
                        f"{self.council_name}: {text!r} gives a span, not a "
                        f"meeting date; leaving it out"
                    )
                    continue

                if filename in _MISLABELLED:
                    date = _MISLABELLED[filename]
                    if date is None:
                        continue
                else:
                    date = self._date(text, filename)
                if date is None:
                    self.logger.warning(f"{self.council_name}: no date in {text!r}")
                    continue
                if years_filter and int(date[:4]) not in years_filter:
                    continue

                name = self._name(body, text)
                papers = meetings.setdefault(
                    (name, date), {"agenda": [], "minutes": []}
                )
                papers[kind].append((text, href))

        results = []
        for (name, date), papers in meetings.items():
            agenda_url = self._pick(papers["agenda"])
            minutes_url = self._pick(papers["minutes"])
            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    @staticmethod
    def _date(text: str, filename: str) -> Optional[str]:
        match = _DATE.search(text)
        if match:
            return (
                parse_date(" ".join(match.groups()), dayfirst=True).date().isoformat()
            )
        # Only an unlabelled card falls through to here. Its filename's
        # ISO prefix is the meeting date on every such card on the page.
        prefix = _ISO_PREFIX.match(filename)
        if prefix:
            return "-".join(prefix.groups())
        return None

    @staticmethod
    def _name(body: str, text: str) -> str:
        name = _BODY_NAMES.get(body)
        if name is None:
            name = body.title()
            if not name.endswith("Meeting"):
                name += " Meeting"
        special = re.search(r"\bspecial\b", text, re.IGNORECASE)
        if body == "COUNCIL MEETING":
            return ("Special " if special else "Ordinary ") + name
        return ("Special " if special else "") + name

    @staticmethod
    def _pick(candidates: list[tuple[str, str]]) -> Optional[str]:
        """One paper per kind, when the page lists a meeting's twice.

        The site was rebuilt in December 2024 and many 2023 papers were
        uploaded again then, so a meeting can have two cards for one paper,
        or an unconfirmed and a confirmed set of minutes. The confirmed
        minutes are the record; otherwise the first card stands.
        """
        if not candidates:
            return None
        confirmed = [url for text, url in candidates if not _UNCONFIRMED.search(text)]
        return confirmed[0] if confirmed else candidates[0][1]
