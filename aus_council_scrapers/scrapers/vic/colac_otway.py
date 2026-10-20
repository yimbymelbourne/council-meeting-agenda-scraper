"""Colac Otway Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The address in the scout notes is a landing page; the listing is its
"Council Meetings - Minutes & Agendas" sub-page. One list
(``OC CL Public Meetings``) holds every meeting, and includes the next one
before its papers are up (27 October 2026, on 20 October).

Papers are filed under ``<h3>Agenda</h3>`` and ``<h3>Minutes</h3>`` (or
"Unconfirmed Minutes"), every link labelled "Download PDF", so
``papers_by = "heading"``. Beside them sit "Livestream Recording",
"Questions Received in Writing" (2020–2022) and "Unconfirmed Resolutions"
sections. The resolutions are a list of decisions, not the minutes, so a
meeting holding only those (the 10 July 2024 Planning Committee) is reported
with its agenda and no minutes. 26 May 2021's agenda is filed as
"26-april-2021-council-agenda.pdf" but is that meeting's agenda (its cover
reads "Wednesday 26 May 2021").

Fetched (``meeting_types``): Council, Unscheduled and Special Council
Meetings (Ordinary and Special Meetings in 2020), and the Planning Committee,
which decides planning permits. Left out is the Submissions Committee, which
hears submissions and reports them to Council, and was the "Special
Committee Meeting" type in 2020 and 2021. It was 7 of 29 rows in 2026, each
a request.

One production year is the listing page and a payload per kept meeting: 23
requests for 2026, above the ~20 aim because the Planning Committee meets
most months.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.vic._regional_opencities import (
    RegionalOpenCitiesScraper,
)


@register_scraper
class ColacOtwayScraper(RegionalOpenCitiesScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 45 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 45

    papers_by = "heading"
    meeting_types = re.compile(
        r"\bCouncil\b|\bPlanning\b|^Ordinary Meeting$|^Special Meeting$"
    )

    def __init__(self):
        super().__init__(
            "colac_otway",
            "VIC",
            "https://www.colacotway.vic.gov.au/Council-the-shire/Our-Council"
            "/Council-Meetings-Agendas-Minutes/Council-Meetings-Minutes-Agendas",
        )
