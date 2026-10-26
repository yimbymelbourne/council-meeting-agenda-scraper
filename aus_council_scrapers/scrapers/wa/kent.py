import datetime
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import filename_of, find_date, find_month
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.kent.wa.gov.au"
_ARCHIVE_URL = f"{_BASE_URL}/council/agendas-minutes/"

# A WordPress archive, 25 posts a page and newest first, one post per meeting:
# "Ordinary Council Meeting – 15 September 2026". The archive carries only
# titles; the agenda, minutes and the meeting's item attachments are linked
# from each post. So every meeting costs a request, and only Council meetings
# (ordinary and special) are fetched. The Audit (Risk and Improvement)
# Committee and the annual electors' meeting are left out: together they add
# a third again to a year's requests. That keeps a production year near ten
# requests: one archive page and the nine or so posts of that year.
#
# Titles from 2022 to 2024 name only the month ("Ordinary Meeting of Council
# – December 2024"). The post date is when the agenda went up, so it is never
# used. The day comes from the post's slug when it has one
# (ordinary-meeting-of-council-20-november-2024), otherwise from the agenda
# and minutes links themselves ("Ordinary Meeting of Council Agenda – 18
# December 2024").
#
# robots.txt disallows only /wp-admin/.

# Item attachments are numbered ("9.1 Attachment 1 – …", "6.1 Unconfirmed
# Ordinary Meeting of Council Minutes – 20 November 2024", which is the last
# meeting's minutes tabled at this one).
_ITEM_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)+")
_NOT_A_PAPER = re.compile(r"attach|appendi|recording|audio|register", re.IGNORECASE)
_AGENDA = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES = re.compile(r"\bminutes\b", re.IGNORECASE)
_CONFIRMED = re.compile(r"(?<!un)confirmed", re.IGNORECASE)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_COUNCIL = re.compile(r"\bordinary\b|\bspecial\b|\bcouncil meeting\b|meeting of council", re.IGNORECASE)
_NOT_COUNCIL = re.compile(r"audit|committee|elector", re.IGNORECASE)


def _spaced(text: str) -> str:
    return re.sub(r"[-_]+", " ", text)


def _doc_date(label: str, url: str) -> Optional[datetime.date]:
    found = find_date(label) or find_date(_spaced(filename_of(url)))
    return found[0] if found else None


@register_scraper
class KentScraper(BaseScraper):
    # One production year measured 18 s from home (10 requests).
    expected_seconds = 18.0

    def __init__(self):
        super().__init__("kent", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    def _posts(self, wanted: set[int]) -> list[tuple[str, str, int]]:
        """(title, URL, year) for each Council meeting post in a wanted year.

        Pages until one ends before the earliest wanted year: the archive is
        newest first, so nothing further on can be wanted.
        """
        posts = []
        url = _ARCHIVE_URL
        while url:
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            years = []
            for link in soup.select(".entry-title a[href]"):
                title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
                post_url = urljoin(url, link["href"])
                found = find_date(title)
                month = find_month(title)
                year = found[0].year if found else (month[0] if month else None)
                if year is None:
                    self.logger.warning(f"{self.council_name}: no year in {title!r}; skipped")
                    continue
                years.append(year)
                if year in wanted and _COUNCIL.search(title) and not _NOT_COUNCIL.search(title):
                    posts.append((title, post_url, year))
            if not years:
                raise ValueError(f"{self.council_name}: no meeting posts on {url}")
            if min(years) < min(wanted):
                break
            older = soup.find("a", string=re.compile(r"Older posts", re.IGNORECASE))
            url = urljoin(url, older["href"]) if older else None
        return posts

    def _papers(self, soup) -> list[tuple[str, str, str]]:
        """(kind, label, URL) for each agenda or minutes linked from a post."""
        content = soup.select_one(".entry-content")
        if content is None:
            return []
        papers = []
        for link in content.find_all("a", href=True):
            url = urljoin(_BASE_URL, link["href"].strip())
            if not filename_of(url).lower().endswith(".pdf"):
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if _ITEM_NUMBER.match(label) or _NOT_A_PAPER.search(label):
                continue
            filename = filename_of(url)
            if _MINUTES.search(label) and _AGENDA.search(label):
                # "22 July 2021 Shire of Kent Agenda and Minutes" is one file,
                # `OCM-MINUTES-JULY-2021-Public.pdf`.
                kind = "minutes" if re.search(r"minutes", filename, re.IGNORECASE) else "agenda"
            elif _MINUTES.search(label):
                kind = "minutes"
            elif _AGENDA.search(label):
                kind = "agenda"
            else:
                continue
            papers.append((kind, label, url))
        return papers

    def _meeting_date(self, title: str, url: str, papers) -> Optional[datetime.date]:
        found = find_date(title) or find_date(_spaced(url.rstrip("/").rsplit("/", 1)[-1]))
        if found:
            return found[0]
        month = find_month(title)
        dates = {
            date
            for _, label, paper_url in papers
            if (date := _doc_date(label, paper_url))
            and (month is None or (date.year, date.month) == month)
        }
        if len(dates) == 1:
            return dates.pop()
        return None

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results = []
        # Archive pages are left to raise: without them there is nothing to
        # read. A post that fails is a meeting missing, so it raises too.
        for title, url, _ in self._posts(wanted):
            papers = self._papers(BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser"))
            date = self._meeting_date(title, url, papers)
            if date is None:
                if papers:
                    self.logger.warning(f"{self.council_name}: cannot date {title!r} ({url}); skipped")
                continue
            if date.year not in wanted:
                continue

            agenda_url = minutes_url = None
            minutes_confirmed = False
            for kind, label, paper_url in papers:
                paper_date = _doc_date(label, paper_url)
                if paper_date and paper_date != date:
                    # Another meeting's paper on this post: July 2021's links
                    # the minutes of the special meeting of 1 July 2021.
                    continue
                if kind == "agenda" and agenda_url is None:
                    agenda_url = paper_url
                elif kind == "minutes":
                    confirmed = bool(_CONFIRMED.search(label) or _CONFIRMED.search(paper_url))
                    if minutes_url is None or (confirmed and not minutes_confirmed):
                        minutes_url, minutes_confirmed = paper_url, confirmed
            if not agenda_url and not minutes_url:
                continue

            results.append(
                ScraperReturn(
                    name="Special Council Meeting" if _SPECIAL.search(title) else "Ordinary Council Meeting",
                    date=date.isoformat(),
                    time=None,
                    webpage_url=url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        if not results:
            # The one legitimate empty answer: a run for the current year in
            # its first quarter, before any of its papers are up (or for a
            # later year). Anything else means the site changed, and [] would
            # be recorded as a successful scrape.
            this_year = clock.current_year()
            if all(y > this_year or (y == this_year and clock.today().month <= 3) for y in wanted):
                self.logger.warning(f"{self.council_name}: no meetings published yet for {sorted(wanted)}")
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
