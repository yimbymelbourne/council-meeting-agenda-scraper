"""Broken Hill City Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary Council
meetings from 2018, upcoming ones included, with a year filter. Standing
committee business papers are on separate content pages under
``/Council/Meetings/Standing-Committees/`` and are not read.

Papers are one flat "Related Information" list labelled by filename, so
``papers_by = "link_text"``: "2609-Open-Business-Paper-Ordinary-Council-
Meeting-held-30-September-2026.pdf", "2607-Open-Minutes-Ordinary-Council-
Meeting-held-29-July-2026.pdf". The business paper is the agenda; the base
class reads "Business Paper" as one and passes over the "Supplementary-
Business-Paper-No.-1". A business paper split into parts
("2511-part-1of4-...", November 2025) is stored as its first part.

Two things in these payloads the base class needed help with:

* The 26 August 2026 minutes link is a bare GUID (``href="31b2b004-..."``),
  which the base class rebuilds as a ``/files/<guid>/`` URL.
* Some payloads carry another meeting's minutes: 29 November 2023 lists the
  minutes of 30 November 2022, the 11 November 2021 extraordinary meeting
  the 24 November 2021 ordinary minutes, and 26 February 2020 the minutes of
  25 March 2020. Every label here carries a full date, so
  ``label_dates_must_match`` drops a link dated for another meeting. The
  council also mistypes the day ("...-24-December-2024-confirmed.pdf" for
  the 18 December 2024 minutes), which the base class allows for.

And one thing this subclass handles itself: through 2022 the minutes are
sometimes "2206-Open-Minute-of-Ordinary-Council-Meeting-29-June-2022.pdf",
singular. The base class passes the singular by on purpose, because a
mayoral minute is a motion rather than the minutes, so a singular "Minute
of the ... Meeting" is taken only when nothing says "Minutes".

Two 2020 extraordinary meetings (13 January, 6 October) label their agenda
only with the meeting's name and date ("2001-Extraordinary-Council-Meeting-
13-January-2020.pdf") beside a file that says "Minutes"; with
``title_only_agenda`` the base class takes that file as the agenda.

One production year is 11 requests: the listing filtered to that year (10
meetings in 2026) and a payload per meeting.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import (
    _NOT_THE_PAPER,
    OpenCitiesMeetingsScraper,
    _label,
    _pdf_href,
)

# "Open-Minute-of-Ordinary-Council-Meeting". A "Mayoral Minute of the
# Ordinary Council Meeting" is a motion the mayor puts to that meeting, not its
# minutes, so the word before "minute" must not be "mayoral".
_SINGULAR_MINUTES = re.compile(
    r"(?<!mayoral[\s-])\bminute[\s-]+of[\s-]+(?:the[\s-]+)?"
    r"(?:ordinary|extraordinary)\b",
    re.IGNORECASE,
)


@register_scraper
class BrokenHillScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    label_dates_must_match = True
    title_only_agenda = True
    # The busiest year since 2020 is 18 meetings: one listing page a year.
    page_size = 50
    # The year-filtered page offers every year (checked 20 October 2026).
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "broken_hill",
            "NSW",
            "https://www.brokenhill.nsw.gov.au/Council/Meetings/Minutes-and-agendas",
        )

    def papers(self, content: BeautifulSoup) -> dict[str, str]:
        papers = super().papers(content)
        if "minutes" in papers:
            return papers
        for anchor in content.find_all("a", href=True):
            href = _pdf_href(anchor)
            label = _label(anchor.get_text(" ", strip=True))
            if (
                href
                and _SINGULAR_MINUTES.search(label)
                and not _NOT_THE_PAPER.search(label)
            ):
                papers["minutes"] = urljoin(self.base_url, href)
                break
        return papers
