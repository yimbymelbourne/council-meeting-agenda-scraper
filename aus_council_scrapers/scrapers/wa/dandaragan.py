import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.dandaragan.wa.gov.au"
_LISTING_URL = _BASE_URL + "/your-shire/council/council-meetings.aspx"

# A CouncilConnect site, but the meetings module is not used: every Council
# meeting since 2017 is on this one content page, so CouncilConnectScraper
# does not apply and one request covers the whole history. Under a heading
# per year ("2026") is a heading per meeting ("26 February 2026", "9 July 2025
# Special Council Meeting") followed by its links: "<date> Agenda &
# Attachments", "<date> Minutes (Signed)", an audio recording, and for some
# meetings each item's attachments ("ITEM 9.1.1 - ..."). Heading levels swap
# between years (year h3 with meeting h2 in 2025-26, the reverse before), so
# headings are told apart by their text, not their level.
#
# Dates come from the headings, never from file names: the 23 April 2026
# minutes are "20260602102844154.pdf" and the 27 February 2025 minutes
# "20270227_...". robots.txt disallows /Profiles/dandaragan/Assets/ModuleData/;
# the papers are under ClientData, and the scraper only links them anyway.
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_DATE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})",
    re.IGNORECASE,
)
_YEAR_HEADING = re.compile(r"^\s*(20\d{2})\s*$")
# Item attachments, recordings and stand-alone attachments are not papers.
_NOT_A_PAPER = re.compile(r"^\s*i?tem\b|recording|audio|^attachment", re.IGNORECASE)
# The annual meeting of electors is not a Council meeting; its minutes are
# listed under the February Council meeting ("7 February 2025 AGM Minutes").
_ELECTORS = re.compile(r"\bAGM\b|electors", re.IGNORECASE)
# "28 November 2024 Minutes & Attachments ( Meeting held 5 December 2024)":
# the meeting was put off a week, and its minutes record 5 December.
_HELD = re.compile(r"held\s+(\d{1,2}\s+[a-z]+\s+20\d{2})", re.IGNORECASE)


def _parse(text: str) -> Optional[datetime.date]:
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    try:
        return datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
    except ValueError:
        return None


@register_scraper
class DandaraganScraper(BaseScraper):
    def __init__(self):
        super().__init__("dandaragan", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        meetings: list[dict] = []
        current: Optional[dict] = None
        in_listing = False
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a"]):
            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
            if element.name == "h1":
                # Sections: "Agendas and Minutes" (ordinary meetings, with some
                # special ones), "Special Council Meetings" (which, as the page
                # is laid out, is followed by the 2017-2019 ordinary meetings),
                # then "Audit Committee Meetings" and "Annual General Meeting
                # of Electors". Only the Council's own meetings are kept.
                lowered = text.lower()
                if "agendas and minutes" in lowered or "special council" in lowered:
                    in_listing = True
                elif "audit" in lowered or "electors" in lowered:
                    in_listing = False
                current = None
                continue
            if element.name != "a":
                if not in_listing or _YEAR_HEADING.match(text):
                    continue
                date = _parse(text)
                if date is None:
                    # A heading after the listing (the page footer) ends it.
                    current = None
                    continue
                current = {
                    "date": date,
                    "heading": text,
                    "agenda": None,
                    "minutes": None,
                    "evidence": text,
                }
                meetings.append(current)
                continue

            if current is None or not element.get("href"):
                continue
            url = urljoin(_LISTING_URL, element["href"].strip())
            if not url.lower().split("?")[0].endswith(".pdf"):
                continue
            if _NOT_A_PAPER.search(text) or _ELECTORS.search(text):
                continue
            label = text.lower()
            file_name = url.rsplit("/", 1)[-1].lower()
            current["evidence"] += f" {text} {file_name}"
            if "minutes" not in label and "agenda" not in label:
                # "4 January 2024 Special Council Meeting" names neither; its
                # file is "20240104_-_4_January_SCM_Agenda___Attachments.pdf".
                label = file_name
            if "minutes" in label:
                if current["minutes"] is None:
                    current["minutes"] = url
                    held = _HELD.search(text)
                    if held and _parse(held.group(1)):
                        current["date"] = _parse(held.group(1))
            elif "agenda" in label:
                if current["agenda"] is None:
                    current["agenda"] = url

        if not meetings:
            raise ValueError(
                f"{self.council_name}: no meeting headings on {_LISTING_URL}"
            )

        # A special meeting is often listed twice, among the ordinary
        # meetings and again under Special Council Meetings, each copy with
        # some of its papers: merge them. The type is read from the heading,
        # the labels or the file names ("..._SCM_Minutes_-_Signed.pdf").
        merged: dict[tuple, dict] = {}
        for m in meetings:
            special = re.search(r"special|\bSCM\b|_SCM_", m["evidence"], re.IGNORECASE)
            name = "Special Council Meeting" if special else "Ordinary Council Meeting"
            key = (m["date"], name)
            if key not in merged:
                merged[key] = {"agenda": None, "minutes": None}
            for slot in ("agenda", "minutes"):
                merged[key][slot] = merged[key][slot] or m[slot]

        results = []
        for (date, name), m in merged.items():
            if date.year not in wanted or date.year < EARLIEST_YEAR:
                continue
            if not m["agenda"] and not m["minutes"]:
                continue  # an upcoming meeting with nothing published yet
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=m["agenda"],
                    minutes_url=m["minutes"],
                    download_url=m["agenda"] or m["minutes"],
                )
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
