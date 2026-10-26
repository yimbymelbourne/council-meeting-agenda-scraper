import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = "https://www.cbcity.nsw.gov.au/your-council/council-meetings-and-minutes"
# The listing is a Drupal view, newest first, paged.
_PAGE_URL = _LISTING_URL + "?sort_by=field_ex_co_cat&sort_order=DESC&page={page}"

# Each meeting is an accordion item — the class name is misspelled in the
# council's own markup — whose heading reads "Tue, 25 Aug 2026, 6pm Ordinary
# Meeting" and whose body links that meeting's documents.
_ACCORDION_ITEM = re.compile(r"accordian-item")
_PAGE_PARAM = re.compile(r"[?&]page=(\d+)")

# Not anchored on word boundaries: some links are labelled with the bare file
# name ("cblpp_4_november_2024_agenda.pdf"), and `_agenda` has no word boundary
# in front of it. Nothing else in these panels — Video, Audio, View More,
# Public Forum — contains either word, so a plain substring is safe here.
_AGENDA_LABEL = re.compile(r"agenda", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"minutes", re.IGNORECASE)
_ATTACHMENT_LABEL = re.compile(r"attachment|supplementary", re.IGNORECASE)

# Meeting names arrive carrying zero-width spaces from the CMS editor.
_INVISIBLE = re.compile(r"[​‌‍﻿]")

# The heading ends with the meeting type; everything before it is date and time.
_TRAILING_PUNCTUATION = " ,-–—"


@register_scraper
class CanterburyBankstownScraper(BaseScraper):
    def __init__(self):
        council = "canterbury_bankstown"
        state = "NSW"
        base_url = "https://www.cbcity.nsw.gov.au"
        super().__init__(council, state, base_url)
        self.default_location = "Cnr of The Mall and Chapel Road, Bankstown"

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _last_page(soup: BeautifulSoup) -> int:
        pages = [
            int(match.group(1))
            for link in soup.find_all("a", href=True)
            if (match := _PAGE_PARAM.search(link["href"]))
        ]
        return max(pages) if pages else 0

    def _meetings_on_page(self, soup: BeautifulSoup) -> list[ScraperReturn]:
        results = []

        for item in soup.find_all(
            lambda tag: tag.name == "div"
            and tag.has_attr("class")
            and any(_ACCORDION_ITEM.search(c) for c in tag["class"])
        ):
            heading = item.find(["h2", "h3", "h4"])
            if not heading:
                continue

            heading_text = _INVISIBLE.sub("", heading.get_text(" ", strip=True))
            date_match = self.date_regex.search(heading_text)
            if not date_match:
                # Not a meeting — the same accordion component is used for
                # explanatory panels elsewhere on the page.
                continue

            time_match = self.time_regex.search(heading_text)
            name = heading_text[date_match.end() :]
            if time_match and time_match.start() >= date_match.end():
                name = heading_text[time_match.end() :]
            name = name.strip(_TRAILING_PUNCTUATION) or "Council Meeting"

            agenda_url = None
            minutes_url = None
            for link in item.find_all("a", href=True):
                label = link.get_text(" ", strip=True)
                if _ATTACHMENT_LABEL.search(label):
                    continue
                href = urljoin(_LISTING_URL, link["href"])
                if _MINUTES_LABEL.search(label):
                    if minutes_url is None:
                        minutes_url = href
                elif _AGENDA_LABEL.search(label):
                    if agenda_url is None:
                        agenda_url = href

            if not agenda_url and not minutes_url:
                continue

            results.append(
                ScraperReturn(
                    name=name,
                    date=date_match.group(),
                    time=time_match.group() if time_match else None,
                    webpage_url=_LISTING_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        wanted = self._wanted_years()
        earliest_wanted = min(wanted)

        html = self.fetcher.fetch_with_requests(_PAGE_URL.format(page=0))
        soup = BeautifulSoup(html, "html.parser")
        last_page = self._last_page(soup)

        results: list[ScraperReturn] = []
        page = 0
        while True:
            found = self._meetings_on_page(soup)
            years = {int(m.date[-4:]) for m in found}
            results.extend(m for m in found if int(m.date[-4:]) in wanted)
            self.logger.debug(f"page {page}: {len(found)} meeting(s) {sorted(years)}")

            # Newest first, so once a whole page predates what we asked for
            # there is nothing left to find on the pages behind it.
            if years and max(years) < earliest_wanted:
                break
            page += 1
            if page > last_page:
                break
            html = self.fetcher.fetch_with_requests(_PAGE_URL.format(page=page))
            soup = BeautifulSoup(html, "html.parser")

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
