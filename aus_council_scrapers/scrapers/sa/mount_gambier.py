"""City of Mount Gambier (SA).

A Craft CMS archive of individual documents, one table row each: title,
committee, type (Agenda, Minutes, Notice, Record of Proceedings, ...) and
the meeting date, linking straight to a PDF on `cdn.mountgambier.sa.gov.au`
(S3, no WAF). Rows are grouped into meetings by committee and date.

The site is not SimpleGov's, so `CraftArchiveScraper` does not fit: its
filter is `?year=YYYY` rather than a date range, the type filter is
`type[]=agenda&type[]=minutes`, and every file sits in one
`/agendas-minutes/` folder, so link text and the type column, not the
folder, say what a file is. With both filters a year is two or three pages
of 40, paged by path (`/archive/p2?...`); production's one year is two
requests.

Only Council, Special Council and the planning bodies are kept: the Council
Assessment Panel (to 2022) and the Limestone Coast Southern Regional
Assessment Panel that replaced it. Audit, CEO review, sports-fund and
briefing-session papers are left out.

A meeting can have several rows of one type: a supplementary agenda typed
"Agenda" beside the main one, in-confidence minutes released later beside
the open minutes, unconfirmed beside confirmed minutes. Supplementary and
in-confidence papers are never used, and confirmed minutes win; see `_rank`.

**Fetching is measured, not guessed.** The site is CloudFront with AWS WAF.
From a home IP on 20 Oct 2026 a requests client sending our identifying
User-Agent got the WAF's 202-with-empty-body challenge, and the same client
sending `BROWSER_USER_AGENT` got the page. So the scraper fetches with
requests as a browser, and if a page still comes back without the archive
(the challenge, as a GitHub runner may get) it switches to Selenium, which
cleared the challenge from home both with and without the headless marker.
Neither path has been measured from a runner.

robots.txt (readable only as a browser) disallows only /cpresources/,
/vendor/, /.env and /cache/.
"""

from __future__ import annotations

import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from aus_council_scrapers import clock
from aus_council_scrapers.base import (
    BROWSER_USER_AGENT,
    BaseScraper,
    ScraperReturn,
    register_scraper,
)
from aus_council_scrapers.constants import EARLIEST_YEAR

_LISTING_URL = "https://www.mountgambier.sa.gov.au/council/council-meetings/minutes-agendas/archive"

# On every archive page, including an empty one, and never on the challenge.
_ARCHIVE_MARKER = 'select[name="year"]'

_MAX_PAGES = 20

# Committee as the archive names it -> meeting name.
_COMMITTEES = {
    "council": "Ordinary Council Meeting",
    "special council": "Special Council Meeting",
    "council assessment panel (cap)": "Council Assessment Panel",
    "limestone coast southern regional assessment panel (lcsrap)": (
        "Limestone Coast Southern Regional Assessment Panel"
    ),
}

_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\b")


_SPECIAL = re.compile(r"special", re.I)

# A supplementary paper is listed as type "Agenda" beside the main agenda,
# sometimes before it (18 June 2024, CAP 21 May 2020), so row order cannot
# pick the agenda. Matched against the file name and the row title together.
_SUPPLEMENTARY = re.compile(
    r"supplementary|\bsupp\b|_sup\b|late[- _]item|addendum", re.I
)
# In-confidence minutes released later sit beside the open minutes (1 July
# 2020). "No-In-Confidence" is the open version and must not match.
_CONFIDENTIAL = re.compile(r"confidential|(?<!no[- ])in[- ]confidence", re.I)
_CONFIRMED = re.compile(r"confirmed", re.I)


def _filename(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])


def _without_cache_buster(url: str) -> str:
    """Drop the `?v=<timestamp>` Craft adds, which changes on re-upload."""
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "v"]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


@register_scraper
class MountGambierScraper(BaseScraper):
    # Measured from a home IP, 20 Oct 2026: the identifying string gets the
    # AWS WAF challenge, this one the page.
    user_agent = BROWSER_USER_AGENT
    # strip_headless_user_agent is left off: the Selenium fallback cleared
    # the challenge from home with and without the HeadlessChrome token.
    # If a runner shows the token being refused (as Adelaide Hills'
    # CloudFront does), opt in then.

    def __init__(self):
        super().__init__("mount_gambier", "SA", "https://www.mountgambier.sa.gov.au")
        self._use_selenium = False

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return set(years_filter)
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _page_url(year: int, page: int) -> str:
        path = _LISTING_URL if page == 1 else f"{_LISTING_URL}/p{page}"
        query = urllib.parse.urlencode(
            [("year", year), ("type[0]", "agenda"), ("type[1]", "minutes")]
        )
        return f"{path}?{query}"

    def _fetch(self, url: str) -> BeautifulSoup:
        if not self._use_selenium:
            soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")
            if soup.select_one(_ARCHIVE_MARKER):
                return soup
            # The AWS challenge answers 202 with an empty body, which
            # requests does not raise on.
            self.logger.warning(
                f"{url} came back without the archive (most likely the AWS WAF "
                f"challenge); switching to Selenium"
            )
            self._use_selenium = True
        html = self.fetcher.fetch_with_selenium(
            url,
            wait_time=30,
            wait_condition=EC.presence_of_element_located(
                (By.CSS_SELECTOR, _ARCHIVE_MARKER)
            ),
        )
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def _offered_years(soup: BeautifulSoup) -> set[int]:
        select = soup.select_one(_ARCHIVE_MARKER)
        return {
            int(option["value"])
            for option in select.find_all("option")
            if (option.get("value") or "").isdigit()
        }

    @staticmethod
    def _cell_text(cell) -> str:
        for label in cell.select(".archive__title-text"):
            label.decompose()
        return re.sub(r"\s+", " ", cell.get_text(" ", strip=True))

    def _rows(self, soup: BeautifulSoup):
        for row in soup.select("div.archive tbody tr"):
            cells = row.find_all("td")
            link = cells[0].find("a", href=True) if cells else None
            if len(cells) < 4 or link is None:
                continue
            committee, kind, when = (self._cell_text(cell) for cell in cells[1:4])
            match = _DATE.search(when)
            if not match:
                self.logger.warning(
                    f"No date in archive row {link.get_text(' ', strip=True)!r}"
                )
                continue
            try:
                date = datetime.datetime.strptime(
                    f"{match.group(1)} {match.group(2).title()} {match.group(3)}",
                    "%d %b %Y",
                ).date()
            except ValueError:
                continue
            title = self._cell_text(cells[0])
            yield committee, kind.lower(), date, link["href"].strip(), title

    @staticmethod
    def _rank(kind: str, text: str) -> Optional[int]:
        """Lower is better; None means the paper is never this meeting's `kind`.

        A supplementary agenda is not the agenda, and in-confidence minutes
        are not the open minutes, so neither is used even when it is the only
        paper of its kind. Confirmed minutes beat the unconfirmed copy (CAP,
        21 January 2021 lists both). Otherwise the archive's order stands.
        """
        if kind == "agenda":
            return None if _SUPPLEMENTARY.search(text) else 0
        if _CONFIDENTIAL.search(text):
            return None
        return 0 if _CONFIRMED.search(text) else 1

    def _merge_split_specials(self, meetings: dict) -> None:
        """Rejoin a special meeting whose papers were filed under two committees.

        In 2020 the archive often lists one of a special meeting's papers
        under "Council" and the other under "Special Council": on 3 and 31
        March 2020 the agenda sits under one and the minutes under the other,
        and the Council's ordinary meetings that month were on other days. A
        Council record holding only an agenda beside a Special Council record
        holding only minutes (or the reverse), on the same date, is one
        meeting, and it is the special one.
        """
        for name, date in list(meetings):
            if name != "Ordinary Council Meeting":
                continue
            ordinary = meetings[(name, date)]
            special = meetings.get(("Special Council Meeting", date))
            if (
                special is None
                or len(ordinary) != 1
                or len(special) != 1
                or set(ordinary) == set(special)
            ):
                continue
            self.logger.info(
                f"{date}: Council {next(iter(ordinary))} and Special Council "
                f"{next(iter(special))} are one special meeting's papers; merged"
            )
            special.update(ordinary)
            del meetings[(name, date)]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        wanted = self._wanted_years()

        # (name, date) -> kind -> (rank, url); the lowest rank wins and, on a
        # tie, the first row listed.
        meetings: dict[tuple[str, datetime.date], dict[str, tuple[int, str]]] = {}
        offered: Optional[set[int]] = None
        for year in sorted(wanted):
            if offered is not None and year not in offered:
                # The filter's options run to next year. An unoffered year
                # would be ignored and page through the whole archive.
                continue
            for page in range(1, _MAX_PAGES + 1):
                soup = self._fetch(self._page_url(year, page))
                if offered is None:
                    offered = self._offered_years(soup)
                    if year not in offered:
                        break
                for committee, kind, date, href, title in self._rows(soup):
                    name = _COMMITTEES.get(committee.lower())
                    if (
                        name is None
                        or kind not in ("agenda", "minutes")
                        or date.year != year
                    ):
                        continue
                    url = urllib.parse.urljoin(_LISTING_URL, href)
                    if name == "Ordinary Council Meeting" and _SPECIAL.search(
                        _filename(url)
                    ):
                        # Filed under the wrong committee: the minutes of the
                        # special meeting of 7 May 2020 are listed as
                        # "Council" ("Special-Council-Minutes-07-07-2020.pdf"),
                        # as is the 1 July 2020 special meeting's agenda.
                        # Moved, they join the rest of their meeting's papers.
                        name = "Special Council Meeting"
                    if not urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
                        # The Council minutes of 15 September 2026 are a .docx.
                        self.logger.warning(
                            f"{name} {date}: {kind} is not a PDF ({url}); skipped"
                        )
                        continue
                    rank = self._rank(kind, f"{_filename(url)} {title}")
                    if rank is None:
                        self.logger.info(
                            f"{name} {date}: {title!r} ({_filename(url)}) is not "
                            f"the {kind}; skipped"
                        )
                        continue
                    papers = meetings.setdefault((name, date), {})
                    if kind not in papers or rank < papers[kind][0]:
                        papers[kind] = (rank, _without_cache_buster(url))
                if not any(
                    re.search(rf"/archive/p{page + 1}\?", anchor["href"])
                    for anchor in soup.find_all("a", href=True)
                ):
                    break
            else:
                self.logger.warning(f"{year}: stopped at the {_MAX_PAGES}-page cap")

        self._merge_split_specials(meetings)

        results = []
        for (name, date), papers in sorted(
            meetings.items(), key=lambda kv: (kv[0][1], kv[0][0])
        ):
            agenda_url = papers["agenda"][1] if "agenda" in papers else None
            minutes_url = papers["minutes"][1] if "minutes" in papers else None
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
            message = (
                f"{self.council_name}: no meetings with papers in {sorted(wanted)}"
            )
            if clock.today() - datetime.date(min(wanted), 1, 1) > datetime.timedelta(
                days=90
            ):
                raise RuntimeError(
                    message + "; the archive markup has probably changed"
                )
            self.logger.warning(message)

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
