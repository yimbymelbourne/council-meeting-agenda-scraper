import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_BASE_URL = "https://www.npsp.sa.gov.au"
_COUNCIL_URL = (
    f"{_BASE_URL}/about_council/council_and_committees/council_agenda_and_minutes"
)
_COMMITTEE_URL = (
    f"{_BASE_URL}/about_council/council_and_committees/committee_agenda_and_minutes"
)

# Both pages are the council's own CMS (theme path /skin/npsp_2019/) and carry
# their whole published history—2024 onwards—in the HTML. Each body gets a
# `div.widget-MeetingList` holding one `<tbody data-year="YYYY">` per year;
# the year "tabs" above it only toggle visibility client-side, so two GETs
# cover every meeting and `years_filter` has nothing left to save.
#
# Rows are "Tuesday, 6 October 2026" | Agenda | Minutes. Neither page says
# what kind of meeting a row is beyond the body it sits under, so the only
# finer distinction available is the "special_" prefix the council puts on
# some filenames (special_cap_agenda_29_january_2026.pdf).
#
# The committee page is included because it is where the Council Assessment
# Panel—the body that decides development applications—publishes. The
# other committees come along with it at no extra request.
_COUNCIL_MEETING = "Council Meeting"

_AGENDA_LABEL = re.compile(r"\bagenda\b", re.IGNORECASE)
_MINUTES_LABEL = re.compile(r"\bminutes\b", re.IGNORECASE)
_SPECIAL_FILE = re.compile(r"(?:^|/|_)special_", re.IGNORECASE)


def _document_url(base_url: str, href: str) -> str:
    # Every href carries a ?v=NNN cache-buster that changes on each render of
    # the page (the same agenda was ?v=526 on one load and ?v=636 on the
    # next). Kept, it would give every document a new URL every night. The
    # file is served the same without it.
    parts = urlsplit(urljoin(base_url, href.strip()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


@register_scraper
class NorwoodPaynehamStPetersScraper(BaseScraper):
    def __init__(self):
        super().__init__("norwood_payneham_st_peters", "SA", _BASE_URL)

    def _body_name(self, widget, page_url: str) -> str | None:
        if page_url == _COUNCIL_URL:
            return _COUNCIL_MEETING
        # On the committee page each widget sits under an <h3> naming the
        # committee. "Norwood Parade Precinct Committee" has a heading but no
        # widget, so the nearest preceding heading is always the right one.
        heading = widget.find_previous(["h2", "h3"])
        return _clean(heading.get_text(" ")) if heading else None

    def _scrape_page(self, page_url: str) -> list[ScraperReturn]:
        html = self.fetcher.fetch_with_requests(page_url)
        soup = BeautifulSoup(html, "html.parser")

        widgets = soup.find_all("div", class_="widget-MeetingList")
        if not widgets:
            raise RuntimeError(
                f"{self.council_name}: no meeting list on {page_url}; "
                f"the page layout has changed"
            )

        # The hrefs are relative ("files/40002_....pdf") and the page sets
        # <base href="https://www.npsp.sa.gov.au/">, so they resolve against
        # the site root. Joined to the page URL instead they point under
        # /about_council/council_and_committees/, which does not exist.
        base = soup.find("base", href=True)
        base_url = urljoin(page_url, base["href"]) if base else page_url

        years_filter = getattr(self, "years_filter", None)
        results: list[ScraperReturn] = []
        for widget in widgets:
            body = self._body_name(widget, page_url)
            if not body:
                self.logger.warning(
                    f"{self.council_name}: a meeting list on {page_url} has "
                    f"no heading to name it by"
                )
                continue

            for tbody in widget.find_all("tbody"):
                year = tbody.get("data-year", "")
                if years_filter and year.isdigit() and int(year) not in years_filter:
                    continue

                for tr in tbody.find_all("tr"):
                    cells = tr.find_all("td")
                    if not cells:
                        continue
                    date_match = self.date_regex.search(_clean(cells[0].get_text(" ")))
                    if not date_match:
                        continue

                    agenda_url = None
                    minutes_url = None
                    for link in tr.find_all("a", href=True):
                        label = link.get_text(" ", strip=True)
                        if _MINUTES_LABEL.search(label) and minutes_url is None:
                            minutes_url = _document_url(base_url, link["href"])
                        elif _AGENDA_LABEL.search(label) and agenda_url is None:
                            agenda_url = _document_url(base_url, link["href"])

                    if not agenda_url and not minutes_url:
                        continue

                    special = any(
                        url and _SPECIAL_FILE.search(urlsplit(url).path)
                        for url in (agenda_url, minutes_url)
                    )
                    results.append(
                        ScraperReturn(
                            name=f"Special {body}" if special else body,
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

        # A failure on either page is left to raise. Each page carries whole
        # bodies—the committee page is the only source for the Council
        # Assessment Panel—so carrying on without one would silently drop
        # them, and losing both would report "0 meetings" as a success.
        results: list[ScraperReturn] = []
        for page_url in (_COUNCIL_URL, _COMMITTEE_URL):
            results.extend(self._scrape_page(page_url))

        if not results:
            # The one legitimate empty answer: production asks only for the
            # current year, and in the first weeks of January nothing for it
            # has been published yet. Any other empty result means the pages
            # broke.
            years_filter = getattr(self, "years_filter", None)
            if years_filter and all(y >= clock.current_year() for y in years_filter):
                self.logger.warning(
                    f"{self.council_name}: no meetings published yet for "
                    f"{sorted(years_filter)}"
                )
            else:
                raise RuntimeError(f"{self.council_name}: found no meetings")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
