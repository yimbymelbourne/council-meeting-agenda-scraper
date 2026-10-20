import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://tsirc.qld.gov.au"
_DOCUMENTS_URL = f"{_BASE_URL}/documents/"

# Torres Strait Island Regional Council files each meeting as a post in a
# WordPress document library (/documents/<slug>/), listed by FacetWP and
# filterable by report type. The listing is rendered server-side, fifteen
# posts a page, newest first: /documents/?_report_type=ordinary-meeting&
# _paged=2. Each meeting's post links its papers as PDFs under wp-content/
# uploads: "Agenda and Reports - September 2026 Ordinary Council Meeting",
# "DRAFT MINUTES - Ordinary Council Mtg - September 2026".
#
# Only Council meetings are read: the ordinary and special report types. The
# council also sits as trustee of the Deed of Grant in Trust land, and from
# August 2026 its trustee papers share a post with the ordinary meeting's;
# those are told apart by their labels and left out, as are the committee
# report types.
_REPORT_TYPES = {
    "ordinary-meeting": "Ordinary Council Meeting",
    "special-meetings": "Special Council Meeting",
}

# A post's title dates the meeting: "Ordinary Meeting – 22 April 2026",
# "Special Meeting: 4 September 2024", "Ordinary Meeting – 24 & 25 March
# 2026" and "– 21-22 July 2026 – Mabuiag" for meetings over two days (filed
# under the first). Ordinary meetings before 2026 are titled by month alone
# ("Ordinary Meeting – December 2025"), and neither their posts nor their
# files name the day, so those meetings are left out rather than dated by
# guesswork. Every special meeting since 2020 has a full date.
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
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
    )
}
_FULL_DATE = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:&|-|–)\s*\d{{1,2}}(?:st|nd|rd|th)?)?\s+{_MONTH}\s+(\d{{4}})",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(20\d\d)\b")

_TRUSTEE = re.compile(r"trustee", re.IGNORECASE)
_MINUTES = re.compile(r"minutes|confirmed|ratified|unconfirmed", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
# Three 2025 special meetings file their agenda without the word: "NOTICE OF
# SPECIAL COUNCIL MEETING - 17 Oct 2025" and "Special Mtg Papers - website
# copy" both open with the agenda and order of business. Taken only when the
# post has no link that says "agenda".
_AGENDA_UNNAMED = re.compile(r"notice\s+of\s+special|\bpapers\b", re.IGNORECASE)
_NOT_THE_PAPERS = re.compile(
    r"attachment|late\s+item|supplementary|addendum", re.IGNORECASE
)


def _full_date(text: str) -> Optional[datetime.date]:
    for day, month, year in _FULL_DATE.findall(text):
        try:
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
        except ValueError:
            continue
    return None


@register_scraper
class TorresStraitIslandScraper(BaseScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 21.9 s for
    # two listing pages and ten meeting posts. Orders dispatch only.
    expected_seconds = 22

    def __init__(self):
        super().__init__("torres_strait_island", "QLD", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _posts(self, report_type: str, earliest: int):
        """(title, post URL) for each meeting post, newest first.

        Paging stops after the first page that reaches back past `earliest`.
        FacetWP renders its pager with JavaScript, so the page count is read
        from the settings it embeds ("total_pages":5).
        """
        page = 1
        while True:
            url = f"{_DOCUMENTS_URL}?_report_type={report_type}"
            if page > 1:
                url += f"&_paged={page}"
            # Not caught: a lost listing page loses every meeting on it.
            html = self.fetcher.fetch_with_requests(url)
            soup = BeautifulSoup(html, "html.parser")
            template = soup.select_one(".facetwp-template")
            if template is None:
                raise RuntimeError(f"{self.council_name}: no document listing on {url}")
            posts = [
                (re.sub(r"\s+", " ", link.get_text(" ", strip=True)), link["href"])
                for link in template.select("a.post-card-title[href]")
            ]
            yield from posts

            years = [
                int(m.group(1)) for title, _ in posts if (m := _YEAR.search(title))
            ]
            total = re.search(r'"total_pages":(\d+)', html)
            if (
                not posts
                or not total
                or page >= int(total.group(1))
                or (years and min(years) < earliest)
            ):
                return
            page += 1

    def _papers(self, post_url: str) -> tuple[Optional[str], Optional[str]]:
        """The agenda and minutes PDFs on a meeting's post."""
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(post_url), "html.parser")
        agenda_url = minutes_url = unnamed_agenda_url = None
        for link in soup.find_all("a", href=True):
            href = urljoin(post_url, link["href"])
            if "/wp-content/uploads/" not in href or not href.lower().endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            text = f"{label} {href.rsplit('/', 1)[-1]}"
            if _TRUSTEE.search(text) or _NOT_THE_PAPERS.search(label):
                continue
            # "CONFIRMED - Special Council Meeting - 6 Mar 2026" is minutes
            # without the word.
            if _AGENDA.search(text) and not _MINUTES.search(label):
                agenda_url = agenda_url or href
            elif _MINUTES.search(text):
                minutes_url = minutes_url or href
            elif _AGENDA_UNNAMED.search(label):
                unnamed_agenda_url = unnamed_agenda_url or href
        return agenda_url or unnamed_agenda_url, minutes_url

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        for report_type, name in _REPORT_TYPES.items():
            for title, post_url in self._posts(report_type, min(wanted)):
                date = _full_date(title)
                if date is None:
                    year = _YEAR.search(title)
                    if year and int(year.group(1)) in wanted:
                        self.logger.info(
                            f"{self.council_name}: {title!r} has no day; left out"
                        )
                    continue
                if date.year not in wanted:
                    continue
                agenda_url, minutes_url = self._papers(post_url)
                if not agenda_url and not minutes_url:
                    continue
                results.append(
                    ScraperReturn(
                        name=name,
                        date=date.isoformat(),
                        time=None,
                        webpage_url=post_url,
                        agenda_url=agenda_url,
                        minutes_url=minutes_url,
                        download_url=agenda_url or minutes_url,
                    )
                )

        results.sort(key=lambda r: (r.date, r.name))
        if not results:
            # The one empty answer that is not a fault: production asks for
            # the current year alone, and before March a small council may not
            # have posted its first paper of the year. Any other empty result
            # means the pages moved or stopped parsing, and returning [] would
            # read downstream as a successful night with no meetings.
            today = clock.today()
            if min(wanted) > today.year or (
                min(wanted) == today.year and today.month < 3
            ):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(wanted)}"
                )
            else:
                raise RuntimeError(
                    f"{self.council_name}: no meetings with documents for "
                    f"{sorted(wanted)}; the pages may have changed"
                )
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
