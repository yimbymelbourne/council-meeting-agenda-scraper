import datetime
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://kingisland.tas.gov.au"
# A WordPress page listing every meeting since 2017 as a `div.item-meeting`:
# a title ("16 September 2025 Council Meeting") and Agenda / Minutes /
# Recording buttons. The papers are all on Google Drive, as a link to the
# file itself or to a folder holding it beside its attachments.
_LISTING_URL = f"{_BASE_URL}/council/meetings-agendas-minutes/"

# drive.google.com/robots.txt disallows everything outside a list of
# allowed prefixes. `/drive/` is allowed and its folder page is
# server-rendered, so folders are read there; the lighter
# `/embeddedfolderview` is not allowed, and neither is `/uc`, the direct
# download. So documents are emitted as `/uc?export=download` links (they
# answer with the PDF itself) but never fetched here, the same emit-only
# treatment as Forbes and Gingin. Crawl-delay is 1 s.
_DRIVE = "https://drive.google.com"
_DRIVE_CRAWL_DELAY = 1.0
_FILE_ID = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)([\w-]{20,})")
_FOLDER_ID = re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]{20,})")

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_TITLE_DATE = re.compile(r"^\s*(\d{1,2})\s+" + _MONTH + r"\s+(\d{4})\s*(.*)$", re.IGNORECASE)
_FULL_DATE = re.compile(r"(?<!\d)(\d{1,2})\s+" + _MONTH + r"\s+(\d{4})", re.IGNORECASE)
_TITLE_YEAR = re.compile(r"\b(20\d\d)\b")

# Choosing the paper in a folder. Folders hold the agenda with its
# attachments, reports and supplementary items, under names like "AGENDA -
# OPEN 19 August 2025 reduced.pdf", "20250429-AGE-OPEN 29 April 2025
# reduced.pdf", "20250128-MIN-OPEN ..." or just "Ordinary Council Meeting
# 15 December 2020.pdf".
_KIND_WORDS = {
    "agenda": re.compile(r"agenda|\bAGE\b", re.IGNORECASE),
    "minutes": re.compile(r"minutes|\bMIN\b", re.IGNORECASE),
}
_NOT_THE_PAPER = re.compile(
    r"attach|appendix|supporting|supplementary|additional|late item|report|"
    r"\bplan\b|strategy|framework|feasibility|fees|policies|"
    # Numbered attachments ("1 - KIC LPS - Zones.pdf"), not a dated name
    # ("20260421- AGENDA - OPEN ...").
    r"^\d{1,2}(\.\d+)?\s*-\s",
    re.IGNORECASE,
)
_OPEN = re.compile(r"\bopen\b|public", re.IGNORECASE)
_MEETING_PAPER = re.compile(r"council meeting|ordinary|special meeting", re.IGNORECASE)
# "AGM Agenda - meeting held in February 2023pdf" lost its dot.
_PDF_NAME = re.compile(r"\.?pdf$", re.IGNORECASE)


def _download_url(file_id: str) -> str:
    return f"{_DRIVE}/uc?export=download&id={file_id}"


def _pick(files: list[tuple[str, str]], kind: str) -> Optional[tuple[str, str]]:
    """The (id, name) of the agenda or minutes among a folder's PDFs."""
    other = "minutes" if kind == "agenda" else "agenda"
    papers = [f for f in files if not _NOT_THE_PAPER.search(f[1])]
    named = [f for f in papers if _KIND_WORDS[kind].search(f[1])]
    # The AGM's folder holds its agenda and its minutes together.
    named = [f for f in named if not _KIND_WORDS[other].search(f[1])] or named
    if named:
        return next((f for f in named if _OPEN.search(f[1])), named[0])
    unnamed = [f for f in papers if not _KIND_WORDS[other].search(f[1])]
    if len(unnamed) > 1:
        # "Ordinary Council Meeting 18 February 2020 reduced.pdf" beside two
        # recreation-plan documents.
        unnamed = [f for f in unnamed if _MEETING_PAPER.search(f[1])]
    return unnamed[0] if len(unnamed) == 1 else None


@register_scraper
class KingIslandScraper(BaseScraper):
    # One production year is the listing plus one Drive folder page per
    # foldered paper, each about 320 KB and a second apart (Crawl-delay), so
    # the cost scales with how many papers are folders. 2026 has 6 so far
    # (11.7 s from home); 2025, where nearly every paper is a folder, took
    # 47.3 s, which is what a full year costs.
    expected_seconds = 47.0

    def __init__(self):
        super().__init__("king_island", "TAS", _BASE_URL)
        self._folders: dict[str, list[tuple[str, str]]] = {}

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _folder(self, folder_id: str) -> Optional[list[tuple[str, str]]]:
        """(file id, name) for each PDF in a shared folder, None if it is gone."""
        if folder_id in self._folders:
            return self._folders[folder_id]
        self.fetcher.sleep(_DRIVE_CRAWL_DELAY)
        try:
            html = self.fetcher.fetch_with_requests(f"{_DRIVE}/drive/folders/{folder_id}")
        except requests.HTTPError as error:
            # A folder the council deleted or unshared costs that paper only.
            # Anything else (a block, a timeout) is left to fail the council.
            if "404" not in str(error):
                raise
            self.logger.warning(f"{self.council_name}: Drive folder {folder_id} is gone")
            return None
        soup = BeautifulSoup(html, "html.parser")
        files = []
        for row in soup.select("tr[data-id]"):
            name = row.find("strong")
            # Sub-folders (the 18 July 2023 agenda folder holds "Agenda" and
            # "Minutes" folders) are not followed: one more request each, for
            # a handful of meetings.
            if name and _PDF_NAME.search(name.get_text(strip=True)):
                files.append((row["data-id"], name.get_text(strip=True)))
        self._folders[folder_id] = files
        return files

    def _paper(self, href: str, kind: str) -> tuple[Optional[str], list[str]]:
        """The document URL for one Agenda or Minutes button, and the names
        of the files it was chosen from (the folder's, or the one file's
        name where the link gives it)."""
        if href.lower().endswith(".pdf") and href.startswith(_BASE_URL):
            return href, [href.rsplit("/", 1)[-1]]
        match = _FILE_ID.search(href)
        if match:
            return _download_url(match.group(1)), []
        match = _FOLDER_ID.search(href)
        if match:
            files = self._folder(match.group(1))
            chosen = _pick(files, kind) if files else None
            if chosen:
                # The chosen file first, so it dates the meeting if it can.
                return _download_url(chosen[0]), [chosen[1]] + [f[1] for f in files]
            if files is not None:
                self.logger.warning(
                    f"{self.council_name}: no {kind} among {[f[1] for f in files]} "
                    f"in folder {match.group(1)}"
                )
        return None, []

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # Left to raise: the listing is the only way to the papers.
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        for item in soup.select("div.item-meeting"):
            title_el = item.select_one(".title")
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
            match = _TITLE_DATE.match(title)
            if match:
                day, month, year, rest = match.groups()
                date: Optional[datetime.date] = datetime.date(
                    int(year), _MONTHS[month[:3].lower()], int(day)
                )
                name = rest.strip(" -–") or "Council Meeting"
            else:
                # "Annual General Meeting 2025" has no day; it is dated
                # below from its papers' file names, or left out.
                year_match = _TITLE_YEAR.search(title)
                if not year_match:
                    continue
                date, year, name = None, year_match.group(1), title
            if int(year) not in wanted:
                continue
            name = re.sub(r"^Council Meetings$", "Council Meeting", name)
            # "Annual General Meeting February 2023" is the AGM.
            name = re.sub(r"\s*(?:\b" + _MONTH + r"\s+)?\d{4}$", "", name, flags=re.IGNORECASE)

            papers: dict[str, str] = {}
            filenames: list[str] = []
            for anchor in item.select(".meeting-buttons a[href]"):
                kind = anchor.get_text(strip=True).lower()
                if kind not in ("agenda", "minutes") or kind in papers:
                    continue
                url, names = self._paper(anchor["href"].strip(), kind)
                filenames.extend(names)
                if url:
                    papers[kind] = url
            if not papers:
                continue

            if date is None:
                # The AGM's own papers say when it sat ("Minutes 2025 AGM 15
                # December 2025.pdf"). Never a guessed day.
                for filename in filenames:
                    # Only the meeting's own papers: the annual report beside
                    # the 2021 agenda is "as at 1 March 2021".
                    if _NOT_THE_PAPER.search(filename) or not any(
                        p.search(filename) for p in _KIND_WORDS.values()
                    ):
                        continue
                    full = _FULL_DATE.search(filename)
                    if full and full.group(3) == year:
                        date = datetime.date(
                            int(year), _MONTHS[full.group(2)[:3].lower()], int(full.group(1))
                        )
                        break
            if date is None:
                self.logger.warning(
                    f"{self.council_name}: {title!r} has no day in its title or "
                    f"papers; left out"
                )
                continue

            agenda_url, minutes_url = papers.get("agenda"), papers.get("minutes")
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            self.logger.warning(
                f"{self.council_name} found no meetings for {sorted(wanted)}"
            )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
