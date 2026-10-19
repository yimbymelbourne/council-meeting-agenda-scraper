"""Mackay Regional Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The meetings module on this page holds the current year only: 10 meetings
for 2026 (checked 20 October 2026). Its year filter also offers 2018, which
is empty. Earlier papers (2023–2025) are on a separate static page,
``/Council/Council-Meetings/Previous-Agendas-and-Minutes``, which this
scraper does not read: its links are labelled only "Agenda" and "Minutes",
several point at another meeting's file (the 26 February 2025 minutes link
is the 26 March file; the 7 February 2024 minutes link is named for 30
October 2024), and it needs a parser of its own. So the fixture covers one
year, and each January the year just ended presumably moves off this module
and out of the scraper's view.

The list is ``LGAQ CL Public Meetings``—the name the form's ``action``
carries after a year postback—not the usual ``OC CL Public Meetings``.

The theme's rows differ from the module's usual markup. There is no
``span.minutes-date`` or ``span.meeting-type``: the trigger's only text is an
``<h2>`` such as "Ordinary Meeting - September 23, 2026" or "Special Budget
Meeting - June 29, 2026". Each listing page is therefore rewritten into the
usual shape as it is fetched (`_normalise_rows`), so the base class's
listing walk, year checks and dedupe apply unchanged. The page also carries
an emergency-announcement button with a ``data-cvid`` of its own; it is not
an accordion row and is never read.

Papers are in a flat "Related information" list labelled by the paper—
"Ordinary Meeting - Agenda - August 26, 2026", "Ordinary Meeting - Minutes -
August 26, 2026"—beside livestream links, so ``papers_by = "link_text"``.
Two 2026 payloads (27 May and 22 April) give the time as "12:00 AM", the
module's value for a time nobody entered; every other meeting is 10:00 AM
or 1:00 PM. A midnight start is reported as no time rather than as a time.

Meeting types are Ordinary and Special meetings only, so nothing is
filtered: one production year is about 11 requests.

The site is behind Akamai (``Server-Timing: ak_p``), which served the
identifying User-Agent without a challenge from a home IP; it has not been
measured from a GitHub runner. robots.txt disallows nothing under
``/Council/Council-Meetings`` or ``OCServiceHandler.axd``.
"""

import re

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from aus_council_scrapers.base import ScraperReturn, register_scraper
from aus_council_scrapers.opencities import ListingRow, OpenCitiesMeetingsScraper

# "Ordinary Meeting - September 23, 2026": the type, then the date after the
# last separator.
_TITLE = re.compile(
    r"^(?P<type>.+?)\s+[-–—]\s+(?P<date>[A-Za-z]+\s+\d{1,2},?\s+\d{4})$"
)


@register_scraper
class MackayScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s
    # (11 requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "LGAQ CL Public Meetings"
    papers_by = "link_text"
    page_size = 100
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "mackay",
            "QLD",
            "https://www.mackay.qld.gov.au/Council/Council-Meetings/Meeting-agendas-minutes-and-videos",
        )

    def _fetch_listing_page(self, url: str, required: bool = False, **kwargs):
        html = super()._fetch_listing_page(url, required, **kwargs)
        return self._normalise_rows(html) if html is not None else None

    def _normalise_rows(self, html: str) -> str:
        """Give each row the date and type spans the base class reads."""
        soup = BeautifulSoup(html, "html.parser")
        for container in soup.find_all("div", class_="accordion-list-item-container"):
            trigger = container.find("a", class_="accordion-trigger")
            title = trigger.find("h2") if trigger else None
            if title is None or container.find("span", class_="minutes-date"):
                continue
            text = re.sub(r"\s+", " ", title.get_text(" ", strip=True))
            match = _TITLE.match(text)
            if not match:
                # Without a date the base class drops the row, so say which.
                self.logger.warning(f"Listing row with no readable date: {text!r}")
                continue
            date = parse_date(match.group("date")).date()
            for css, value in (
                ("minutes-date", f"{date.day} {date:%B %Y}"),
                ("meeting-type", match.group("type")),
            ):
                span = soup.new_tag("span", attrs={"class": css})
                span.string = value
                trigger.append(span)
        return str(soup)

    def build_return(
        self, content: BeautifulSoup, row: ListingRow
    ) -> ScraperReturn | None:
        record = super().build_return(content, row)
        if record is not None and record.time == "12:00 AM":
            record.time = None
        return record
