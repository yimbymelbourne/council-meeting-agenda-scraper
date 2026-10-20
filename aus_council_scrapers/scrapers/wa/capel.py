"""Shire of Capel (South West WA).

The site is CouncilConnect, but its meetings module is no use here: the
meeting pages under ``/council-meetings/past/<year>`` carry no documents (all
ten 2025 ordinary meetings sampled were empty). The papers are on one
hand-edited content page, ``minutes-agendas.aspx``, so a whole history is one
request.

That page is a set of Bootstrap tabs, one ``div.tab-pane`` per year (2021–2026
in October 2026), each opening with ``<h2>2026</h2>``. Within a year, an
``<h2>`` starts each body—"Council Meetings", "Audit, Risk and Improvement
Committee", "Electors Meeting" and so on—and under it every meeting is a label
such as "Ordinary Council Meeting | 28 October" followed by a ``<blockquote>``
of links: "Agenda", "Minutes" or "Confirmed Minutes", and beside them late
items, notices of motion, amended items and attachments.

Only the "Council Meetings" section is read: the ordinary and special meetings
of council. The committees are advisory (audit, bush fire, economic
development) and none is a planning body.

Being typed by hand, the page is inconsistent, and each of these is real:

* The label has no year; the tab gives it. 2021 and 2022 label most ordinary
  meetings just "Meeting | 19 January".
* The label is usually a ``<p>`` before the blockquote, sometimes a bare
  ``<span>`` (26 March 2025), and once inside the blockquote itself
  (28 August 2024). So the label is the last "Name | day Month" text seen
  before the blockquote's first link.
* 2021–2023 agendas are SharePoint sharing links on shireofcapel.sharepoint.com,
  whose robots.txt is ``Disallow: /``, and a sharing link is a viewer page,
  not the file. Those meetings keep their minutes and go without an agenda.
* 25 May 2022 links one file as both "Agenda" and "Confirmed Minutes"; it is
  the agenda (its first page reads "AGENDA - Ordinary Council Meeting - 25
  May 2022").

The PDFs answer 406 unless the request's Accept header includes ``*/*``, as
Kwinana's and Joondalup's do. Our fetcher's Accept list does not, but the
scraper only emits the URLs and never fetches them; a browser or a client
sending ``*/*`` gets the file.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from dateutil.parser import parse as parse_date

from aus_council_scrapers import clock
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper
from aus_council_scrapers.constants import EARLIEST_YEAR

_BASE_URL = "https://www.capel.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/council/your-council/council-committee-meetings/minutes-agendas.aspx"
)

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october"
    "|november|december"
)
# "Ordinary Council Meeting | 28 October", "Meeting | 19 January",
# "Special Council meeting | 2 June".
_LABEL = re.compile(
    rf"(?P<name>[A-Za-z][A-Za-z ]*?)\s*\|\s*(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{_MONTHS})\b",
    re.IGNORECASE,
)

_SECTION = re.compile(r"^council meetings$", re.IGNORECASE)
_AGENDA = re.compile(r"^agenda$", re.IGNORECASE)
_MINUTES = re.compile(r"^(?:confirmed\s+|unconfirmed\s+)?minutes$", re.IGNORECASE)


@register_scraper
class CapelScraper(BaseScraper):
    def __init__(self):
        super().__init__("capel", "WA", _BASE_URL)

    def _wanted_years(self) -> set[int]:
        years_filter = getattr(self, "years_filter", None)
        if years_filter:
            return {int(year) for year in years_filter}
        return set(range(EARLIEST_YEAR, clock.current_year() + 3))

    @staticmethod
    def _name(raw: str) -> str:
        name = " ".join(raw.split())
        if name.lower() == "meeting":
            # 2021–2022's bare "Meeting" in the Council Meetings section is
            # the ordinary meeting; the specials there say so.
            return "Ordinary Council Meeting"
        return name[0].upper() + name[1:].replace(" meeting", " Meeting")

    def _document(self, href: str) -> Optional[str]:
        url = urljoin(_LISTING_URL, href.strip())
        host = urlparse(url).netloc.lower()
        if host != urlparse(_BASE_URL).netloc:
            # SharePoint sharing links: robots-disallowed viewer pages.
            return None
        if not urlparse(url).path.lower().endswith(".pdf"):
            return None
        return url

    def _meeting(
        self, label: re.Match, quote: Tag, year: int
    ) -> Optional[ScraperReturn]:
        agenda_url = minutes_url = None
        for link in quote.find_all("a", href=True):
            text = " ".join(link.get_text(" ", strip=True).split())
            if _AGENDA.match(text):
                agenda_url = agenda_url or self._document(link["href"])
            elif _MINUTES.match(text):
                minutes_url = minutes_url or self._document(link["href"])
        if agenda_url and agenda_url == minutes_url:
            # One file under both labels (25 May 2022). Its filename says
            # which it is when it says either; otherwise it is the agenda,
            # which is published first and is the link left pointing at the
            # old file when the minutes go up.
            name = urlparse(agenda_url).path.rsplit("/", 1)[-1].lower()
            if "minute" in name:
                agenda_url = None
            else:
                minutes_url = None
        if not agenda_url and not minutes_url:
            return None
        date = parse_date(f"{label['day']} {label['month']} {year}", dayfirst=True).date()
        return ScraperReturn(
            name=self._name(label["name"]),
            date=date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url or minutes_url,
        )

    def _read_pane(self, pane: Tag, year: int) -> list[ScraperReturn]:
        """Walk one year's tab in document order.

        Text seen since the last blockquote is kept, and a blockquote takes
        the last label in it. Text inside the blockquote ahead of its first
        link counts too, for the 28 August 2024 label typed there.
        """
        results: list[ScraperReturn] = []
        state = {"section": None, "text": []}

        def label_for(quote: Tag) -> Optional[re.Match]:
            leading = []
            for node in quote.descendants:
                if isinstance(node, Tag) and node.name == "a":
                    break
                if isinstance(node, NavigableString):
                    leading.append(str(node))
            for text in (" ".join(leading), " ".join(state["text"])):
                found = list(_LABEL.finditer(" ".join(text.split())))
                if found:
                    return found[-1]
            return None

        def walk(node: Tag) -> None:
            for child in node.children:
                if isinstance(child, NavigableString):
                    state["text"].append(str(child))
                    continue
                if not isinstance(child, Tag):
                    continue
                if child.name == "h2":
                    state["section"] = " ".join(child.get_text(" ", strip=True).split())
                    state["text"] = []
                    continue
                if child.name == "blockquote":
                    in_council = bool(state["section"] and _SECTION.match(state["section"]))
                    label = label_for(child)
                    state["text"] = []
                    if not in_council:
                        continue
                    if label is None:
                        self.logger.warning(
                            f"capel: {year} papers with no meeting label: "
                            f"{[a.get('href') for a in child.find_all('a', href=True)][:3]}"
                        )
                        continue
                    record = self._meeting(label, child, year)
                    if record:
                        results.append(record)
                    continue
                walk(child)

        walk(pane)
        return results

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(_LISTING_URL), "html.parser")
        wanted = self._wanted_years()
        panes: dict[int, Tag] = {}
        for pane in soup.select("div.tab-pane"):
            heading = pane.find("h2")
            text = heading.get_text(strip=True) if heading else ""
            if re.fullmatch(r"20\d\d", text):
                panes[int(text)] = pane
        if not panes:
            # The page was fetched but holds no year tabs: it has been
            # rebuilt, and an empty list would read as a quiet council.
            raise RuntimeError(f"capel: no year tabs found on {_LISTING_URL}")

        missing = sorted(y for y in wanted if y <= clock.current_year() and y not in panes)
        if missing and max(missing) >= min(panes):
            self.logger.warning(f"capel: no tab for {missing}; tabs are {sorted(panes)}")

        results: list[ScraperReturn] = []
        for year in sorted(panes, reverse=True):
            if year in wanted and year >= EARLIEST_YEAR:
                results.extend(self._read_pane(panes[year], year))
        if not results:
            self.logger.warning(f"capel: no council meetings with papers for {sorted(wanted)}")
        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results
