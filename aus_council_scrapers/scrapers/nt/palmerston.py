import re
from typing import Optional
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://palmerston.nt.gov.au"

# One page per year, `/your-council/council-meetings/<year>`, each listing every
# council meeting of that year—upcoming ones included, with "Not available
# yet" in place of their documents. The bare `/your-council/council-meetings`
# shows the current year too, but the year path keeps cassette URLs stable
# across a new year. A year with nothing scheduled answers 200 with no
# meetings.
_YEAR_URL = _BASE_URL + "/your-council/council-meetings/{year}"

# Each meeting is a `div.meeting` whose `h4.meeting__title` is the date, with
# " — Special Council Meeting" appended for a special meeting since late 2024.
# Its file items are labelled Agenda, Minutes, Attachments and Note.
#
# The labels are not to be trusted on their own: confirmed minutes have been
# uploaded under "Agenda" (18 August 2020, 1 February 2022), late items sit
# beside the agenda, and some agendas are named only "20241210 - Ordinary
# Council Meeting - 10 December 2024". So each document under Agenda or
# Minutes is classified by its own name first, and by its label only when the
# name says nothing either way.
_MINUTES = re.compile(r"minutes", re.IGNORECASE)
_AGENDA = re.compile(r"agenda", re.IGNORECASE)
# "Agenda with attachments" is the agenda—the 15 June 2021 meeting has no
# other—so only a bare attachment is excluded.
_NOT_A_PAPER = re.compile(
    r"late item|additional|(?<!with )attachment|supplementary|tabled|correspondence",
    re.IGNORECASE,
)
_SPECIAL = re.compile(r"\bspecial\b", re.IGNORECASE)
_TITLE_DATE = re.compile(
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+\d{4}",
    re.IGNORECASE,
)


@register_scraper
class PalmerstonScraper(BaseScraper):
    def __init__(self):
        super().__init__("palmerston", "NT", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _papers(meeting) -> tuple[Optional[str], Optional[str], str]:
        """(agenda_url, minutes_url, text of both) for one meeting block."""
        agenda_url = None
        minutes_url = None
        texts = []
        for item in meeting.select(".meeting__file-item"):
            label_tag = item.select_one(".meeting__file-label")
            label = label_tag.get_text(strip=True) if label_tag else ""
            if label not in ("Agenda", "Minutes"):
                continue
            for link in item.find_all("a", href=True):
                href = urljoin(_BASE_URL, link["href"])
                # The 2020 pages link the YouTube livestream from here.
                if not href.lower().endswith(".pdf"):
                    continue
                text = f"{link.get_text(' ', strip=True)} {unquote(href.rsplit('/', 1)[-1])}"
                texts.append(text)
                if _NOT_A_PAPER.search(text):
                    continue
                if _MINUTES.search(text):
                    kind = "minutes"
                elif _AGENDA.search(text):
                    kind = "agenda"
                else:
                    kind = label.lower()
                if kind == "agenda" and agenda_url is None:
                    agenda_url = href
                elif kind == "minutes" and minutes_url is None:
                    minutes_url = href
        return agenda_url, minutes_url, " ".join(texts)

    def _parse_page(self, html: str, page_url: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for meeting in soup.select("div.meeting"):
            title_tag = meeting.select_one(".meeting__title")
            if not title_tag:
                continue
            title = re.sub(r"\s+", " ", title_tag.get_text(" ", strip=True))
            date_match = _TITLE_DATE.search(title)
            if not date_match:
                continue

            agenda_url, minutes_url, texts = self._papers(meeting)
            if not agenda_url and not minutes_url:
                # Upcoming meetings, and meetings held entirely in
                # confidence, have nothing published.
                continue

            # The title names the type when it is not an ordinary meeting,
            # but only since late 2024; before that, a special meeting is
            # known only from its papers ("Special Council Meeting Agenda").
            qualifier = title[date_match.end() :].strip(" -–—")
            if qualifier:
                name = qualifier
            elif _SPECIAL.search(texts):
                name = "Special Council Meeting"
            else:
                name = "Ordinary Council Meeting"

            results.append(
                ScraperReturn(
                    name=name,
                    date=date_match.group(),
                    time=None,
                    webpage_url=page_url,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        results: list[ScraperReturn] = []
        for year in sorted(wanted):
            url = _YEAR_URL.format(year=year)
            # A failed page is left to raise: production asks for one year,
            # so this is usually the only request, and swallowing it would
            # report a blocked or broken site as a council with no meetings.
            html = self.fetcher.fetch_with_requests(url)
            found = self._parse_page(html, url)
            if not found and year <= clock.current_year():
                # Future years are legitimately empty; a past or current one
                # is not.
                self.logger.warning(
                    f"{self.council_name}: no meetings with papers on {url}"
                )
            results.extend(found)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
