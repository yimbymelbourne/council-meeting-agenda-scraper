import datetime
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.councilconnect import CouncilConnectScraper

_BASE_URL = "https://www.gingin.wa.gov.au"
_SEARCH_URL = f"{_BASE_URL}/council-meetings/search"
_SEARCH_CONTROL = (
    "ctl00$ContentPlaceHolder1$CouncilMeetings_usercontrol$cntrlSearchModule"
)

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
# "Tuesday 15 September 2026, Ordinary Meeting of Council" on the listing;
# "ordinary-council-meeting-15-september-2026" in a meeting page's address.
_DATE = re.compile(
    r"(?<!\d)(\d{1,2})[\s-]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s-]+(\d{4})",
    re.IGNORECASE,
)
# A meeting page, optionally one of its documents:
# /council-meetings/<type>/<slug>/<id>[/documents/<file>].
_MEETING_PAGE = re.compile(
    r"^(?P<page>/council-meetings/(?P<type>[a-z0-9-]+)/(?P<slug>[^/]+)/\d+)"
    r"(?:/documents/(?P<file>[^/]+))?/?$"
)


def _date_in(text: str) -> Optional[datetime.date]:
    for day, month, year in _DATE.findall(text):
        try:
            return datetime.date(int(year), _MONTHS[month[:3].lower()], int(day))
        except ValueError:
            continue
    return None


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@register_scraper
class GinginScraper(CouncilConnectScraper):
    """Shire of Gingin—CouncilConnect, with a year listing of its own shape.

    Upcoming meetings are read as the base class reads them: from the
    upcoming page, through each meeting's own page, where the agenda is.

    Past meetings are not. Gingin's year listing (/council-meetings/past/
    <year>) is a run of `div.council-meeting-info` blocks, each headed "Tuesday
    15 September 2026, Ordinary Meeting of Council" with the minutes linked
    inline, and no link to the meeting's page. Agendas are taken down once a
    meeting has passed, from the listing and the meeting page alike, so a
    past meeting has minutes only.

    The inline links point into the module's file store,
    /Profiles/gingin/assets/moduledata/councilmeetings/<guid>/<version>/
    <file>.pdf, where the version moves whenever the meeting is edited. That
    path is also, case aside, the one robots.txt disallows, so the scraper
    never fetches it. The stable address is the meeting page's
    <page>/documents/<file lowercased>, as on East Fremantle, but that needs
    the meeting page, which the listing does not give. The council-meetings
    search does: its "View All" results link every meeting page from mid
    2023, newest first, 30 to a page. So past meetings are matched to their
    pages by a document's filename, or by type and date, and given the
    stable address. A meeting older than the search reaches (before mid
    2023) is left out: its only address is in the disallowed file store,
    and council-alerts would fetch whatever URL is emitted. Production reads
    only the current year, which the search covers.
    """

    # The /past index goes back to 2017, but nothing before 2023 can be
    # emitted (see above), so those listings are not read.
    first_year = 2023

    # One production year, measured 20 Oct 2026 from a home IP: 12.6 s for
    # eight requests (the year listing, three search requests, the upcoming
    # page and two meeting pages). Orders dispatch only.
    expected_seconds = 13

    def __init__(self):
        super().__init__("gingin", "WA", _BASE_URL)

    # --- the search, for meeting pages --------------------------------------

    @staticmethod
    def _form_data(soup: BeautifulSoup, target: str) -> dict[str, str]:
        form = soup.find("form")
        if form is None:
            raise RuntimeError(f"gingin: no search form on {_SEARCH_URL}")
        data = CouncilConnectScraper._form_fields(form)
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        return data

    def _meeting_pages(self, earliest: int):
        """Index the search's "View All" results back to `earliest`.

        Returns {page URL: (type slug, date or None)} for every meeting page
        linked, and {lowercased filename: {page URLs}} for every document.
        The date is read from the page's address ("...-15-september-2026")
        or its title; a few addresses carry none (".../audit-risk-and-
        improvement-committee-meeting/291"). Pages are followed with the
        pager's Next button until one reaches back past `earliest`, or there
        is no next page.
        """
        pages: dict[str, tuple[str, Optional[datetime.date]]] = {}
        files: dict[str, set[str]] = {}

        # Not caught: without the search, current-year minutes would go out
        # under addresses that move, and each move is a new meeting in
        # council-alerts.
        soup = BeautifulSoup(
            self.fetcher.fetch_with_requests(_SEARCH_URL), "html.parser"
        )
        html = self.fetcher.fetch_with_requests(
            _SEARCH_URL,
            method="POST",
            data=self._form_data(soup, f"{_SEARCH_CONTROL}$bViewAll"),
        )
        while True:
            soup = BeautifulSoup(html, "html.parser")
            results = soup.select_one(".cm-search-results")
            dates = []
            for link in results.find_all("a", href=True) if results else []:
                match = _MEETING_PAGE.match(
                    urlparse(urljoin(_BASE_URL, link["href"])).path
                )
                if not match:
                    continue
                page_url = urljoin(_BASE_URL, match.group("page"))
                date = _date_in(match.group("slug"))
                if match.group("file"):
                    files.setdefault(unquote(match.group("file")).lower(), set()).add(
                        page_url
                    )
                else:
                    date = date or _date_in(link.get("title") or "")
                if date:
                    dates.append(date)
                if page_url not in pages or (date and pages[page_url][1] is None):
                    pages[page_url] = (match.group("type"), date)

            following = soup.find("button", class_="rdpPageNext")
            # On the last page the Next button's handler starts "return
            # false", like the First and Prev buttons on the first page.
            if (
                not dates
                or min(dates).year < earliest
                or following is None
                or (following.get("onclick") or "").startswith("return false")
            ):
                return pages, files
            html = self.fetcher.fetch_with_requests(
                _SEARCH_URL,
                method="POST",
                data=self._form_data(soup, following["name"]),
            )

    @staticmethod
    def _page_for(date, type_slug, links, pages, files) -> Optional[str]:
        """The meeting page a listing block belongs to, or None.

        By type and date first: the page's address is made from its title,
        which names both. Failing that, by a document's filename, but only
        to a page of the same type whose date, where it has one, agrees.
        Filenames alone are not enough: "final-minutes_compressed.pdf" is
        both the 30 June 2026 and the 13 August 2024 special meetings'.
        """
        by_meeting = [
            url
            for url, (kind, day) in pages.items()
            if kind == type_slug and day == date
        ]
        if len(by_meeting) == 1:
            return by_meeting[0]
        for _, _, url in links:
            candidates = {
                page
                for page in files.get(unquote(url.rsplit("/", 1)[-1]).lower(), ())
                if pages.get(page, (None, None))[0] == type_slug
                and pages[page][1] in (None, date)
            }
            if len(candidates) == 1:
                return candidates.pop()
        return None

    # --- the year listing ----------------------------------------------------

    def _past_meetings(self, years: list[int], seen: set[str]) -> list[ScraperReturn]:
        blocks = []
        for year in years:
            listing_url = f"{self.base_url}/council-meetings/past/{year}"
            # As in the base: a failed listing raises, except the new year's
            # 404 before its first meeting has been entered.
            try:
                pages = list(self._listing_pages(listing_url))
            except requests.HTTPError as e:
                response = getattr(e, "response", None)
                status = response.status_code if response is not None else None
                # A replayed failure carries only its message.
                not_found = status == 404 or str(e).startswith("404")
                if year == clock.current_year() and not_found:
                    self.logger.info(f"No listing yet for {year}: {listing_url}")
                    continue
                raise
            for soup in pages:
                self._labels.update(self._type_labels(soup))
                for block in soup.select(".council-meeting-info"):
                    meeting = self._block(block, listing_url)
                    if meeting and meeting[0].year == year:
                        blocks.append(meeting)
        if not blocks:
            return []

        pages, files = self._meeting_pages(min(years))
        results = []
        for date, name, links, listing_url in blocks:
            page_url = self._page_for(date, _slugify(name), links, pages, files)
            if page_url is None:
                # The listing's own links point into the file store, which
                # robots.txt disallows (case aside, and IIS ignores case).
                # council-alerts downloads every document URL emitted, so
                # emitting one would have production fetch a disallowed path.
                # A meeting with no page found is therefore left out. Before
                # mid-2023 that is expected: the search reaches no further
                # back. In the current year the search covers every meeting,
                # so a miss means it changed shape, and is raised.
                if date.year == clock.current_year():
                    raise RuntimeError(
                        f"{self.council_name}: no meeting page found for "
                        f"{name} {date} in the meetings search"
                    )
                self.logger.info(
                    f"{self.council_name}: no meeting page for {name} {date}; "
                    f"left out"
                )
                continue
            links = [
                (group, label, self._stable_document_url(page_url, url))
                for group, label, url in links
            ]
            seen.add(page_url)
            agenda_url, minutes_url = self._pick_documents(links)
            if not agenda_url and not minutes_url:
                continue
            results.append(
                ScraperReturn(
                    name=self._name(name, _slugify(name), self._labels),
                    date=date.isoformat(),
                    time=None,
                    webpage_url=page_url or listing_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def _block(self, block, listing_url: str):
        """(date, name, [(group, label, url)], listing url) for one listing block."""
        heading = block.find("h2")
        # The heading's separator arrives escaped twice: "2026,&nbspOrdinary".
        text = re.sub(
            r"&nbsp;?|\s+", " ", heading.get_text(" ", strip=True) if heading else ""
        )
        date = _date_in(text)
        if date is None:
            self.logger.warning(
                f"{self.council_name}: undated meeting {text!r} on {listing_url}"
            )
            return None
        name = text.split(",", 1)[1].strip() if "," in text else ""
        links = []
        for documents in block.select(".meeting-documents"):
            group = ""
            for element in documents.find_all(["h3", "a"]):
                if element.name == "h3":
                    group = element.get_text(" ", strip=True)
                    continue
                href = element.get("href")
                if not href:
                    continue
                label = element.get("title") or element.get_text(" ", strip=True)
                label = re.sub(
                    r"^(?:Click to download\s+)?(?:Click here to view\s+)?", "", label
                )
                links.append((group, label, urljoin(listing_url, href)))
        return date, name, links, listing_url
