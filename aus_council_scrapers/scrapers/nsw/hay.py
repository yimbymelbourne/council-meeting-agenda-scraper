import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from requests.utils import requote_uri

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = (
    "https://www.hay.nsw.gov.au/Inside-Hay-Shire-Council/Council-Meetings-and-Reports"
)

# A DNN page with one flat list of documents (title link plus a "Download"
# button to the same file) mixing meeting papers from August 2024 on with
# annual reports, plans and strategies. Nothing older is online. One request
# covers the whole history.
#
# Labels and file names are typed by hand and disagree in both directions:
# "Draft Ordinary Meeting Minutes 16th December 2025" links "Business Paper
# 16th December 2025.pdf" (the business paper, by its cover page), and "Draft
# Minutes Ordinary Meeting 28th April 2026" links "Draft Ordinary Meeting
# Minutes 22nd April 2025.pdf", the year before's. So the kind of paper is
# read from the file name first, and a paper whose file name dates it to
# another meeting is dropped.
#
# Eight business papers from August 2024 to October 2025 are linked under
# /Portals/0/CouncilReports/ but answer 404 there; on 20 Oct 2026 each one
# answered 200 with its PDF at the portal root (/Portals/0/<same name>), so
# those links are rewritten. They are named one by one rather than by a rule:
# other papers of the same years work where they are linked, and several 2026
# ones do not exist at the root, so a blanket rewrite would break them.
# Checking each link live instead would cost a request per paper.
_MOVED_TO_ROOT = {
    "Ordinary Business Paper 27th August 2024.pdf",
    "Business Paper December 2024 Ordinary Meeting.pdf",
    "Extraordinary Business Paper - 29th January 2025.pdf",
    "Business Paper 25 February 2025 Ordinary Meeting.pdf",
    "Extraordinary Business Paper 31st July 2025.pdf",
    "Business Paper 26th August 2025.pdf",
    "Business Paper September 2025.pdf",
    "Hay Shire Council Business Paper October 2025.pdf",
}
# The 27 May 2025 minutes are linked as a .docx that answers 404 at that path,
# at the portal root and as a .pdf (checked 20 Oct 2026). With nothing to
# point at, the link is dropped, and that meeting with it.
_DEAD = {"Draft Ordinary Meeting Minutes 27th May 2025.docx"}
#
# The site's PDFs answer 406 to the fetcher's default Accept header and 200 to
# `Accept: */*`; the scraper only links them, so this matters only to anyone
# checking the links with the project's fetcher.
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
# "27th August 2024", "Tuesday 24th February 2026", "24th Februrary 2026",
# "17th December  2024", "22nd October2024".
_FULL_DATE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s_]*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s_]*(20\d{2})",
    re.IGNORECASE,
)
_YYYYMMDD = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_MONTH_YEAR = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b",
    re.IGNORECASE,
)


def _dates(text: str) -> list[datetime.date]:
    found = []
    for day, month, year in _FULL_DATE.findall(text):
        try:
            found.append(
                datetime.date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
            )
        except ValueError:
            pass
    for y, m, d in _YYYYMMDD.findall(text):
        try:
            found.append(datetime.date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return found


def _kind(text: str) -> Optional[str]:
    text = text.lower()
    if "minutes" in text:
        return "minutes"
    if "business paper" in text or "business_paper" in text:
        return "agenda"
    return None


@register_scraper
class HayScraper(BaseScraper):
    def __init__(self):
        super().__init__("hay", "NSW", "https://www.hay.nsw.gov.au")

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

        meetings: dict[tuple, dict] = {}
        undated = []
        seen_urls = set()
        found_any = False
        for link in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if label.lower() == "download":
                continue  # the button beside each title, to the same file
            href = link["href"].strip()
            if "/Portals/" not in href:
                continue
            # Hrefs carry raw spaces; the ?ver= cache-buster is kept as given.
            url = requote_uri(urljoin(_LISTING_URL, href))
            file_name = unquote(url.split("?")[0].rsplit("/", 1)[-1])
            if file_name in _DEAD:
                continue
            if file_name in _MOVED_TO_ROOT and "/Portals/0/CouncilReports/" in url:
                url = url.split("?")[0].replace(
                    "/Portals/0/CouncilReports/", "/Portals/0/"
                )
            kind = _kind(file_name) or _kind(label)
            if kind is None or url in seen_urls:
                continue
            seen_urls.add(url)
            found_any = True
            extra = "extraordinary" in f"{label} {file_name}".lower()
            meeting_type = "Extraordinary" if extra else "Ordinary"

            label_dates = _dates(label)
            file_dates = _dates(file_name)
            date = (label_dates or file_dates or [None])[0]
            if date is None:
                undated.append((label, url, kind, meeting_type))
                continue
            if file_dates and not any(
                abs((d - date).days) <= 3 or (d.month, d.day) == (date.month, date.day)
                for d in file_dates
            ):
                self.logger.warning(
                    f"{self.council_name}: {label!r} links {file_name!r}, another "
                    f"meeting's paper; left out"
                )
                continue
            if date.year not in wanted:
                continue
            meeting = meetings.setdefault(
                (date, meeting_type), {"agenda": None, "minutes": None}
            )
            if meeting[kind] is None:
                meeting[kind] = url

        if not found_any:
            raise ValueError(
                f"{self.council_name}: no business papers or minutes on {_LISTING_URL}"
            )

        # "Business Paper September 2025" and four others give only the month.
        # Each such month holds one meeting of that type whose minutes are
        # dated, so the paper goes there; with none or two it is left out.
        for label, url, kind, meeting_type in undated:
            month_year = _MONTH_YEAR.search(label)
            same_month = []
            if month_year:
                month = _MONTHS.index(month_year.group(1)[:3].lower()) + 1
                year = int(month_year.group(2))
                if year not in wanted:
                    continue
                same_month = [
                    key
                    for key in meetings
                    if (key[0].year, key[0].month, key[1])
                    == (year, month, meeting_type)
                ]
            if len(same_month) == 1 and meetings[same_month[0]][kind] is None:
                meetings[same_month[0]][kind] = url
            else:
                self.logger.warning(
                    f"{self.council_name}: no day for {label!r}; left out"
                )

        results = []
        for date, meeting_type in sorted(meetings, reverse=True):
            m = meetings[(date, meeting_type)]
            results.append(
                ScraperReturn(
                    name=f"{meeting_type} Council Meeting",
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
