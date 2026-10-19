import re
import urllib.parse

from bs4 import BeautifulSoup

from aus_council_scrapers.alyka import (
    PageTypeListingScraper,
    filename_of,
    find_date,
    text_without_date,
    tidy_meeting_name,
)
from aus_council_scrapers.base import (
    ScraperReturn,
    _merge_split_meetings,
    register_scraper,
)

_BASE_URL = "https://www.kwinana.wa.gov.au"
_LISTING_URL = (
    f"{_BASE_URL}/council/council-and-city-administration/minutes-and-agendas"
)

# Kwinana's listing is one `li.row` per meeting — "Ordinary Council Meeting -
# 23 September 2026" — with its files in a collapsed panel: agenda, minutes,
# a separate attachments book since mid-2025, and a video link.
#
# The page's year filter (`FileReleaseDate`) is what bounds the cost, and it
# matters here more than at most councils: the server renders the fragment
# slowly, so the whole history since 2016 takes 36 s to arrive and one year
# about 4 s. Its "release date" is the meeting's own — each year's bucket
# holds exactly that year's meetings, checked for 2024 and 2026 — so asking
# for the wanted years loses nothing at the year boundary.
#
# The document links are Kentico `/getattachment/` URLs. They answer 406 to a
# request whose Accept header does not include `*/*` or `application/pdf` —
# this project's fetcher sends neither — and 200 `application/pdf` to a
# browser, curl, or Node's fetch. The URLs are emitted as they are.
#
# The meeting-type column is not reliable (Boola Maara committee meetings are
# filed under "Ordinary Council Meeting"), so the name comes from the title.

# Labels are "Agenda - <meeting> - <date>", occasionally the bare filename.
# "Agenda - Reports - ..." is the agenda proper; "Agenda-Attachments-..." and
# "Attachments - ..." are the attachment book, which is not.
_AGENDA = re.compile(r"^\s*agenda\b(?![\s-]*attachment)", re.IGNORECASE)
_MINUTES = re.compile(r"^\s*minutes\b", re.IGNORECASE)
# Papers that sit beside a meeting's agenda without being it. The 14 December
# 2022 Ordinary Council Meeting lists "Agenda-Late-and-Urgent-Business-..."
# ahead of the agenda proper, and both start with "Agenda"; taken in order,
# the 22 MB late-items paper would have been stored as the agenda.
_SUPPLEMENTARY = re.compile(r"\blate\b|urgent|addendum|supplementary", re.IGNORECASE)


def _release_year(value: str):
    match = re.search(r"\[(\d{4})", value or "")
    return int(match.group(1)) if match else None


@register_scraper
class KwinanaScraper(PageTypeListingScraper):
    # One production year, measured 19 Oct 2026 from a home IP in full
    # 135-council runs: 9.5 s at 10 workers, 15.1 s at 6. Orders dispatch
    # only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 12

    listing_url = _LISTING_URL
    # A cassette asks for the whole history in one fragment (275 meetings
    # since 2020), so the page is sized to hold it with room to grow.
    PAGE_SIZE = 1000

    def __init__(self):
        super().__init__("kwinana", "WA", _BASE_URL)

    @staticmethod
    def _kind(label: str, url: str):
        """Agenda, minutes or neither, from a link's label or else its file.

        Most labels lead with the document type. Some are just the filename,
        and a few filenames bury it: "Ordinary-Council-Meeting-Agenda-23-
        November-2022.pdf", "Audit-and-Risk-Committee-Meeting-Minutes-...".
        """
        if _SUPPLEMENTARY.search(label) or _SUPPLEMENTARY.search(filename_of(url)):
            return None
        for text in (label, filename_of(url)):
            if _MINUTES.match(text):
                return "minutes"
            if _AGENDA.match(text):
                return "agenda"
        name = filename_of(url).lower()
        if "attachment" in name:
            return None
        if "minutes" in name:
            return "minutes"
        if "agenda" in name:
            return "agenda"
        return None

    def _documents(self, row) -> dict:
        found = {}
        for link in row.select(".minuteandagenda-content a[href]"):
            url = urllib.parse.urljoin(_BASE_URL, link["href"])
            if "/getattachment/" not in url:
                continue  # the YouTube recording
            # The label leads with the document's name; the size and
            # "(opens in a new tab)" trail it in their own spans.
            label = (link.find(string=True, recursive=False) or "").strip() or (
                link.get_text(" ", strip=True)
            )
            kind = self._kind(label, url)
            if kind:
                found.setdefault(kind, url)
        return found

    def scraper(self) -> list[ScraperReturn]:
        self.logger.info(f"Starting {self.council_name} scraper")

        config = self._listing_config(self._listing_page())
        wanted = self._wanted_years()
        # Options look like "date=[20260101 TO 20261231]", one per year that
        # has meetings.
        release_years = [
            value
            for value in self.checkbox_values(config, "FileReleaseDate")
            if _release_year(value) in wanted
        ]
        if not release_years:
            self.logger.warning(
                f"{self.council_name}: the year filter offers none of "
                f"{sorted(wanted)}; nothing to fetch"
            )
            return []

        fragment = BeautifulSoup(
            self._search(config, {"FileReleaseDate": release_years}), "html.parser"
        )
        rows = fragment.select("li.row")
        self._warn_if_full(len(rows), "the listing")

        expected = fragment.find("input", id="recordCountValue")
        if expected and expected.get("value", "").isdigit():
            if int(expected["value"]) != len(rows):
                self.logger.warning(
                    f"{self.council_name}: listing reports {expected['value']} "
                    f"meetings but carried {len(rows)}"
                )

        results = []
        for row in rows:
            title_element = row.find(class_="minuteandagenda-title")
            title = title_element.get_text(" ", strip=True) if title_element else ""
            documents = self._documents(row)

            # One title omits its date ("Boola Maara Aboriginal Consultative
            # Committee", 2 December 2024); its documents' labels carry it.
            found = find_date(title)
            if not found:
                labels = " ".join(
                    a.get_text(" ", strip=True)
                    for a in row.select(".minuteandagenda-content a")
                )
                found = find_date(labels)
            if not found:
                self.logger.info(f"{self.council_name}: no date for {title!r}")
                continue
            date = found[0]
            if date.year not in wanted:
                continue

            meeting = self._meeting(
                name=tidy_meeting_name(text_without_date(title)) or "Council Meeting",
                date=date,
                webpage_url=_LISTING_URL,
                agenda_url=documents.get("agenda"),
                minutes_url=documents.get("minutes"),
            )
            if meeting:
                results.append(meeting)

        # One meeting is occasionally listed twice, once with its agenda and
        # once with its minutes (26 June 2024).
        results = _merge_split_meetings(results)
        # The listing is in no particular order; newest first reads better.
        results.sort(key=lambda r: r.date, reverse=True)

        self._log_result(results, f"{len(rows)} listed meetings")
        return results
