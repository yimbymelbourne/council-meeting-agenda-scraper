import re
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date
from requests.utils import requote_uri

from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

_BASE_URL = "https://www.flinders.tas.gov.au"
_AGENDAS_URL = f"{_BASE_URL}/agendas/"
_MINUTES_URL = f"{_BASE_URL}/minutes/"

# Flinders Council (Furneaux Group) keeps its agendas and its minutes on two
# separate pages, each holding everything back to 2019 (older papers are on
# /archives-agendas and /archives-minutes, before EARLIEST_YEAR). Two requests
# cover the whole history, so a production year costs the same two.
#
# The agendas page is a run of month headings ("September 2026", "December
# 2024 - Special Meeting"), each followed by that meeting's papers: an
# "Agenda Index", the "Agenda 23 September 2026" itself and its annexures,
# and until 2023 every report attachment as its own link (160-200 a year).
# Only the link labelled "Agenda <date>" is the agenda. Its date is the
# meeting's; folder and file names are not, since a July 2026 agenda sits
# under 2026.08.26/2026.07.22/ and the 2023 special meetings are filed as
# 2022.
#
# The minutes page labels each set "2026.09.23 Confirmed Minutes Council
# Meeting", "... Special Council Meeting" or "... Unconfirmed Minutes AGM".
# The label is again what is read, not the file (one "Confirmed" set links an
# unconfirmed file).

_AGENDA_LABEL = re.compile(
    r"^(?:Ordinary Council Meeting\s+)?Agenda\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
    re.IGNORECASE,
)
_MINUTES_LABEL = re.compile(
    r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(?:\w+\s+)?Minutes\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_UNCONFIRMED = re.compile(r"unconfirmed", re.IGNORECASE)

# Minutes whose label gives the wrong day, found by reading the PDF. Keyed by
# filename; the value is the date the minutes themselves state.
_MISDATED = {
    # Labelled "2023.04.04 Confirmed Minutes Special Council Meeting"; the
    # minutes are of the special meeting of 3 April 2023, whose agenda is
    # labelled the 3rd.
    "2022.04.03 CONFIRMED MINUTES Special Council Meeting.pdf": "2023-04-03",
}

ORDINARY = "Ordinary Council Meeting"
SPECIAL = "Special Council Meeting"
AGM = "Annual General Meeting"


@register_scraper
class FlindersTasScraper(BaseScraper):
    # Refused from GitHub-hosted runners (403, 405 or a connection timeout,
    # measured 20 Oct 2026 by running every state shard from a runner) and
    # reachable from a home connection, so it goes through the residential
    # egress. See AGENTS.md, "Councils that block GitHub's runners".
    egress = "residential"

    def __init__(self):
        super().__init__("flinders_tas", "TAS", _BASE_URL)

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")
        agendas = self._agendas(self.fetcher.fetch_with_requests(_AGENDAS_URL))
        minutes = self._minutes(self.fetcher.fetch_with_requests(_MINUTES_URL))
        years_filter = getattr(self, "years_filter", None)

        # Council meetings pair on the date alone: the agenda label calls the
        # 26 May 2020 meeting special and its minutes call it ordinary (its
        # agenda's own filename agrees with the minutes), so the minutes'
        # word wins where both exist. The AGM falls on the same night as the
        # December ordinary meeting and is kept apart.
        keys = sorted(set(agendas) | set(minutes), reverse=True)
        results = []
        for key in keys:
            date, body = key
            if years_filter and int(date[:4]) not in years_filter:
                continue
            agenda = agendas.get(key)
            minute = minutes.get(key)
            if body == AGM:
                name = AGM
            elif minute:
                name = minute[0]
            else:
                name = agenda[0]
            agenda_url = agenda[1] if agenda else None
            minutes_url = minute[1] if minute else None
            results.append(
                ScraperReturn(
                    name=name,
                    date=date,
                    time=None,
                    webpage_url=_AGENDAS_URL if agenda_url else _MINUTES_URL,
                    agenda_url=agenda_url,
                    minutes_url=minutes_url,
                    download_url=agenda_url or minutes_url,
                )
            )

        self.logger.info(f"{self.council_name} scraper found {len(results)} meetings")
        return results

    def _agendas(self, html: str) -> dict[tuple[str, str], tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        base = self._base(soup, _AGENDAS_URL)
        found: dict[tuple[str, str], tuple[str, str]] = {}
        for heading in soup.find_all("h2"):
            heading_text = heading.get_text(" ", strip=True)
            for link in self._links_under(heading):
                label = link.get_text(" ", strip=True)
                match = _AGENDA_LABEL.match(label)
                if not match or not link["href"].lower().endswith(".pdf"):
                    continue
                try:
                    date = parse_date(match.group(1), dayfirst=True).date().isoformat()
                except (ValueError, OverflowError):
                    self.logger.warning(f"{self.council_name}: no date in {label!r}")
                    continue
                special = re.search(
                    r"special", f"{label} {heading_text}", re.IGNORECASE
                )
                name = SPECIAL if special else ORDINARY
                url = requote_uri(urljoin(base, link["href"]))
                key = (date, "council")
                # "Agenda 16 July 2019" labels two links; the one filed
                # under that date is the agenda, and the other is August's.
                if key in found and not self._filed_under(url, date):
                    continue
                found[key] = (name, url)
        return found

    @staticmethod
    def _links_under(heading):
        for element in heading.find_all_next(["h2", "a"]):
            if element.name == "h2":
                return
            if element.get("href"):
                yield element

    def _minutes(self, html: str) -> dict[tuple[str, str], tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        base = self._base(soup, _MINUTES_URL)
        found: dict[tuple[str, str], tuple[str, str]] = {}
        for link in soup.find_all("a", href=True):
            label = link.get_text(" ", strip=True)
            match = _MINUTES_LABEL.match(label)
            if not match or not link["href"].lower().endswith(".pdf"):
                continue
            year, month, day = (int(g) for g in match.groups()[:3])
            date = _MISDATED.get(
                unquote(link["href"].rsplit("/", 1)[-1]),
                f"{year:04d}-{month:02d}-{day:02d}",
            )
            rest = match.group("rest")
            if re.search(r"\bAGM\b|annual general", rest, re.IGNORECASE):
                key, name = (date, AGM), AGM
            elif re.search(r"special", rest, re.IGNORECASE):
                key, name = (date, "council"), SPECIAL
            elif re.search(r"\bpublic\b", rest, re.IGNORECASE):
                # "2022.08.29 Confirmed Minutes - Fin Fish Farming Public
                # Meeting": a public meeting, not a meeting of the Council.
                continue
            else:
                # Everything else is an ordinary meeting. The labels are
                # typed by hand ("2025.07.23 Confirmed Minutes Councl
                # Meeting"), so requiring the word "council" dropped July
                # 2025, whose agendas page has no heading either.
                key, name = (date, "council"), ORDINARY
            url = requote_uri(urljoin(base, link["href"]))
            # 25 October 2023 has a confirmed and an unconfirmed set; the
            # confirmed set is the record.
            if key in found and _UNCONFIRMED.search(label):
                continue
            found[key] = (name, url)
        return found

    @staticmethod
    def _base(soup, page_url: str) -> str:
        # The papers are linked relative ("client-assets/images/...") to a
        # <base href> of the site root, not to the page.
        base = soup.find("base", href=True)
        return urljoin(page_url, base["href"]) if base else page_url

    @staticmethod
    def _filed_under(url: str, date: str) -> bool:
        return date.replace("-", ".") in url
