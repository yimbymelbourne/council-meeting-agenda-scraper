import calendar
import re
from collections import defaultdict
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR
from aus_council_scrapers.pdf_dates import meeting_date_from_papers

_BASE_URL = "https://www.kowanyama.qld.gov.au"
_LISTING_URL = f"{_BASE_URL}/council/council-meetings-agendas-and-minutes/"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({"sept": 9, "sep": 9})
_MONTH = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)


@register_scraper
class KowanyamaScraper(BaseScraper):
    """Kowanyama Aboriginal Shire Council: one WordPress page.

    Headings "2026 Agendas", "2026 Minutes" and "2026 Notices" each sit over
    a list of links labelled by month alone ("January 2026", "June Special
    Meeting 2026", "April (Special Meeting) 2025"). The day is read from the
    PDF: the minutes first, a few hundred KB opening "Kowanyama Aboriginal
    Shire Council January Council Meeting Minutes 27 January 2026", then the
    agenda pack, whose cover reads "Council Meeting Agenda Tuesday, 25 August
    2026". A paper whose PDF names no day in its label's month is left out:
    the labels are typed by hand, and the March 2023 "agenda" is that
    meeting's minutes, the "Special April Meeting 2024" minutes the March
    swearing-in. Notices of meeting are not papers. robots.txt is a 404.
    """

    # One listing request, then one PDF read per meeting in the year.
    expected_seconds = 35.0

    def __init__(self):
        super().__init__("kowanyama", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def scraper(self) -> list[ScraperReturn]:
        wanted = self._wanted_years()
        html = self.fetcher.fetch_with_requests(_LISTING_URL)
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("main") or soup

        # (year, month, name) -> {"agenda": url, "minutes": url}
        meetings: dict[tuple, dict] = defaultdict(dict)
        year = kind = None
        for el in content.find_all(["h1", "h2", "h3", "h4", "h5", "a"]):
            if el.name != "a":
                heading = el.get_text(" ", strip=True)
                found = _YEAR.search(heading)
                year = int(found.group(1)) if found else None
                lowered = heading.lower()
                kind = (
                    "minutes"
                    if "minutes" in lowered
                    else "agenda" if "agenda" in lowered else None
                )
                continue
            href = (el.get("href") or "").strip()
            label = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if not (year and kind and label) or ".pdf" not in href.lower():
                continue
            month = _MONTH.search(label)
            if not month:
                continue
            filename = unquote(urlparse(href).path.rsplit("/", 1)[-1]).lower()
            other = "agenda" if kind == "minutes" else "minutes"
            if other in filename and kind not in filename:
                # Filed under the wrong heading: the March 2023 "agenda" is
                # "20230322_March-Council-Meeting-Minutes2.pdf".
                self.logger.info(
                    f"kowanyama: skipping {label!r} {kind}: file {filename!r}"
                )
                continue
            label_year = _YEAR.search(label)
            key = (
                int(label_year.group(1)) if label_year else year,
                _MONTHS[month.group(1).lower()],
                "Special Meeting" if _SPECIAL.search(label) else "Ordinary Meeting",
            )
            meetings[key].setdefault(kind, urljoin(_LISTING_URL, href))

        if not meetings:
            raise RuntimeError(f"kowanyama: no agendas or minutes on {_LISTING_URL}")

        results = []
        undated = []
        for (year, month, name), papers in sorted(meetings.items()):
            if year not in wanted:
                continue
            agenda, minutes = papers.get("agenda"), papers.get("minutes")
            date = meeting_date_from_papers(
                self.fetcher, [minutes, agenda], year, month, logger=self.logger
            )
            if date is None:
                undated.append(f"{calendar.month_name[month]} {year} {name}")
                continue
            results.append(
                ScraperReturn(
                    name=name,
                    date=date.isoformat(),
                    time=None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda,
                    minutes_url=minutes,
                    download_url=agenda or minutes,
                )
            )
        if undated:
            self.logger.warning(f"kowanyama: left out, no day in the PDFs: {undated}")
        if not results:
            today = clock.today()
            if undated or not (wanted == {today.year} and today.month <= 3):
                raise RuntimeError(
                    f"kowanyama: no dated meeting in {sorted(wanted)}; undated: {undated}"
                )
            self.logger.warning(f"kowanyama: no papers for {sorted(wanted)} yet")
        return results
