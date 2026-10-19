import datetime
import re
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup

from aus_council_scrapers import clock
from aus_council_scrapers.alyka import (
    PageTypeListingScraper,
    filename_says_agenda_only,
    filename_says_minutes_only,
    find_date,
    quote_url,
    text_without_date,
)
from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.ionata import filename_date, reconcile_date

_BASE_URL = "https://www.amrshire.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/shire-and-council/council/council-meeting-agendas-and-minutes"
)

# Shire of Augusta Margaret River, on Alyka's page-type listing (see
# `aus_council_scrapers/alyka.py`). Not `pub-augusta.escribemeetings.com`,
# which is Augusta in Ontario.
#
# The fragment is one accordion item per meeting, headed "Ordinary Council
# Meeting - 28 January 2026", holding a list of documents each under an
# `<h4>` label: Agenda, Minutes, Item (late items and addenda), Attachments,
# Meeting recording. Only Agenda and Minutes are read. The year filter
# (`DocMeetingDateYear`) is the meeting's year, so production is the listing
# page plus one POST. Its "0001" bucket holds undated Sustainability Advisory
# Committee minutes from 2017-2019, before EARLIEST_YEAR, and is not asked for.
#
# Only Council meetings (ordinary and special) and General Electors Meetings
# are kept. The rest are the Shire's advisory committees—bush fire,
# emergency management, audit, sustainability, grants, advocacy—none of which
# decides planning matters, and whose entries are the least reliable on the
# page: the 2020 bush fire and emergency committees file their agendas under
# "Item" and a no-quorum notice under "Minutes", and two Advocacy Committee
# entries link a 2026 agenda in their minutes slot. Every document is on the
# listing, so this is a choice about what is worth storing, not about cost.
_KEPT_MEETINGS = re.compile(r"\bcouncil meeting\b|\belectors\b", re.IGNORECASE)

# Most filenames open with the code of the body that met: OM or OCM for an
# ordinary meeting, SM or SCM for a special one, GEM for electors, and the
# committees' own (SAC, BFAC, LEMC, ARMC, ARIC). A file whose code names a
# different body is that body's paper, wherever it is filed. Two entries need
# this: "Ordinary Council Meeting - 15 February 2022" holds only the
# Sustainability Advisory Committee's papers (SAC-Minutes-15_02_2022(1).pdf),
# and the General Electors Meeting of 27 January 2021 links, as its minutes,
# a copy of that night's ordinary meeting minutes (OM-27_01_21-MINS(1).pdf,
# headed "Ordinary Council MINUTES"). A filename with no code says nothing.
_BODY_CODE = re.compile(
    r"(?<![A-Za-z])(OCM|OM|SCM|SM|GEM|SAC|BFAC|LEMC|ARMC|ARIC)(?![A-Za-z])"
)
_CODE_BODY = {
    "OCM": "ordinary",
    "OM": "ordinary",
    "SCM": "special",
    "SM": "special",
    "GEM": "electors",
}
_HEADING_BODY = (
    (re.compile(r"\bspecial\b", re.IGNORECASE), "special"),
    (re.compile(r"\belectors\b", re.IGNORECASE), "electors"),
    (re.compile(r"\bordinary\b", re.IGNORECASE), "ordinary"),
)

# The 27 October 2021 entry files its agenda (OM-27_10_21-AG.pdf) under
# "Item", the label for late items and addenda. When nothing is labelled
# Agenda, an Item whose filename calls itself the agenda and names this
# meeting's date is taken as it; a late item or addendum never is.
_AGENDA_NAME = re.compile(r"(?<![A-Za-z])(?:AG|agenda)(?![A-Za-z])", re.IGNORECASE)
_NOT_THE_AGENDA = re.compile(r"late|addend|urgent|item|attach|minute", re.IGNORECASE)


def _filename(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path).rsplit("/", 1)[-1]


def _other_body(filename: str, heading: str) -> bool:
    codes = set(_BODY_CODE.findall(filename))
    if not codes:
        return False
    body = next((b for pattern, b in _HEADING_BODY if pattern.search(heading)), None)
    return body not in {_CODE_BODY.get(code) for code in codes}


# Minutes are linked under the CMS's admin path
# (/kentico_admin/awcontent/...), agendas under the public one
# (/awcontent/...). Both serve the same file publicly and robots.txt allows
# both, but the admin path is the one a council locks down, so the public
# path is stored.
_ADMIN_PREFIX = "/kentico_admin/awcontent/"


def _document_url(href: str) -> str:
    url = quote_url(urllib.parse.urljoin(_BASE_URL, href.strip()))
    parts = urllib.parse.urlsplit(url)
    if parts.path.startswith(_ADMIN_PREFIX):
        parts = parts._replace(path="/awcontent/" + parts.path[len(_ADMIN_PREFIX) :])
    return urllib.parse.urlunsplit(parts)


_DOCUMENT_SUFFIXES = (".pdf", ".docx", ".doc")


def _is_pdf(url: Optional[str]) -> bool:
    return bool(url) and _filename(url).lower().endswith(".pdf")


def _named_date(url: str):
    return filename_date(urllib.parse.unquote(url))


@register_scraper
class AugustaMargaretRiverScraper(PageTypeListingScraper):
    listing_url = _LISTING_URL

    def __init__(self):
        super().__init__("augusta_margaret_river", "WA", _BASE_URL)

    def _pick(self, urls: list[str], heading_date) -> Optional[str]:
        """One document of a kind, preferring the file dated for this meeting.

        An entry occasionally carries two files under one label: the 11
        November 2020 meeting lists the 28 October minutes before its own.
        """
        # A PDF beats a Word copy of the same paper, whatever their order.
        urls = sorted(urls, key=lambda url: not _is_pdf(url))
        for url in urls:
            if _named_date(url) == heading_date:
                return url
        return urls[0] if urls else None

    def _parse_item(self, item) -> Optional[ScraperReturn]:
        header = item.select_one(".accordion-header")
        heading = " ".join(header.get_text(" ", strip=True).split()) if header else ""
        found = find_date(heading)
        if not found:
            self.logger.warning(f"{self.council_name}: no date in {heading!r}")
            return None
        heading_date = found[0]
        name = text_without_date(heading)
        if not _KEPT_MEETINGS.search(name):
            return None

        papers: dict[str, list[str]] = {"agenda": [], "minutes": [], "item": []}
        for entry in item.select("ul.doclist > li"):
            label = entry.find("h4")
            link = entry.find("a", href=True)
            if not label or not link:
                continue
            kind = label.get_text(" ", strip=True).lower()
            if kind not in papers:
                continue
            url = _document_url(link["href"])
            filename = _filename(url)
            # The 24 November 2021 agenda is only on the page as a Word file
            # (OM-24_11_21-AG.docx). It is kept, and stored in
            # `agenda_html_url` rather than `agenda_url`, as
            # `AlykaScraper._meeting` does with Kwinana's Word agenda: the PDF
            # fields promise a PDF, and dropping the file would leave that
            # meeting with minutes and no agenda.
            if not filename.lower().endswith(_DOCUMENT_SUFFIXES):
                continue
            if _other_body(filename, name):
                continue
            if kind == "agenda" and filename_says_minutes_only(url):
                continue
            if kind == "minutes" and filename_says_agenda_only(url):
                continue
            papers[kind].append(url)

        if not papers["agenda"]:
            papers["agenda"] = [
                url
                for url in papers["item"]
                if _is_pdf(url)
                and _AGENDA_NAME.search(_filename(url))
                and not _NOT_THE_AGENDA.search(_filename(url))
                and _named_date(url) == heading_date
            ]

        agenda_url = self._pick(papers["agenda"], heading_date)
        minutes_url = self._pick(papers["minutes"], heading_date)
        if not agenda_url and not minutes_url:
            return None

        # The heading is typed separately from the files. Filenames here are
        # wrong more often than headings—PUBLIC-OM_09_02_22-Agenda.pdf is the
        # 23 February 2022 agenda, OM-25-11-2023-Agenda_1.pdf the 25 October
        # 2023 one, and the 7 December 2022 special meeting's minutes are
        # SM_20_10_21_MINUTES.pdf—so a single filename never moves a meeting
        # and never costs it its document. When the agenda and the minutes
        # both name the same other date, the heading is the odd one out: the
        # entry headed 30 September 2024 holds an agenda and minutes both for
        # 25 September 2024, and both papers open "Ordinary Council Meeting 25
        # September 2024". `reconcile_date` takes that majority.
        documents = {
            kind: _named_date(url)
            for kind, url in (("agenda", agenda_url), ("minutes", minutes_url))
            if url
        }
        meeting_date, _ = reconcile_date(heading_date, None, documents)
        if meeting_date != heading_date:
            self.logger.info(
                f"{self.council_name}: {heading!r} holds papers for {meeting_date}; "
                f"dated by the papers"
            )

        agenda_pdf = agenda_url if _is_pdf(agenda_url) else None
        minutes_pdf = minutes_url if _is_pdf(minutes_url) else None
        return ScraperReturn(
            name=name,
            date=meeting_date.isoformat(),
            time=None,
            webpage_url=_LISTING_URL,
            agenda_url=agenda_pdf,
            minutes_url=minutes_pdf,
            agenda_html_url=None if agenda_pdf else agenda_url,
            minutes_html_url=None if minutes_pdf else minutes_url,
            download_url=agenda_pdf or minutes_pdf,
        )

    def _meetings(self, fragment: str) -> list[ScraperReturn]:
        soup = BeautifulSoup(fragment, "html.parser")
        items = soup.select("div.accordion-item")
        self._warn_if_full(len(items), "a year")
        return [m for m in (self._parse_item(item) for item in items) if m]

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        config = self._listing_config(self._listing_page())
        offered = {
            int(v)
            for v in self.checkbox_values(config, "DocMeetingDateYear")
            if v.isdigit() and int(v) > 1
        }
        wanted = self._wanted_years()
        if offered:
            years = sorted(wanted & offered, reverse=True)
        else:
            self.logger.warning(
                f"{self.council_name}: could not read the year filter; "
                f"asking for every wanted year"
            )
            years = sorted(wanted, reverse=True)

        results: list[ScraperReturn] = []
        seen: set[tuple] = set()
        for _, fragment in self._each_year(
            years,
            lambda year: self._search(config, {"DocMeetingDateYear": [str(year)]}),
        ):
            for meeting in self._meetings(fragment):
                key = (meeting.name, meeting.date)
                if meeting.cleaned_date.year not in wanted or key in seen:
                    continue
                seen.add(key)
                results.append(meeting)

        if (
            not results
            and years
            and clock.today() - datetime.date(min(years), 1, 1)
            > datetime.timedelta(days=90)
        ):
            # Two Council meetings a month: a requested year three months
            # old that answered with none of them is a changed fragment, not
            # a quiet year. A year barely begun only warns, in `_log_result`.
            raise RuntimeError(
                f"{self.council_name}: no Council meetings with papers in {years}; "
                f"the listing markup has probably changed"
            )
        self._log_result(results, f"years {years}")
        return results
