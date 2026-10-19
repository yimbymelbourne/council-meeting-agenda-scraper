"""Kempsey Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Council meetings from 2020,
upcoming ones included, with a year filter—and, beside them, the Public
Forum held the day before most meetings and a one-off Oaths and
Affirmations Ceremony. A public forum's "Agenda" is a list of speakers, not
a Council meeting's paper, and each listed meeting costs a payload request,
so ``meeting_types`` keeps the Council meetings only (Ordinary and
Extraordinary; "Ordinary Meeting" up to 2021, "Ordinary Council Meeting"
since). The listing has 126 rows since 2020 (checked 20 October 2026), and
this keeps 79 of them: it drops 46 public forums and the ceremony. 13 of
those forums (14 October 2024 to 19 October 2026) carry no year tag, so no
year's filter returns them; ``bare_page_rows`` reads the bare first page in
case a Council meeting is ever left untagged the same way.

Papers are filed under headings, so ``papers_by = "heading"``, and the
headings have changed shape almost every year. Up to 2021 they are a plain
"Agenda" and "Draft Minutes - <date>". Since 2022 the agenda's heading is
mostly the meeting's own title, "Ordinary Council Meeting - 20 October
2026", whose first PDF is the agenda and whose item attachments follow as
untitled sections; with ``title_heading_agenda`` the base class reads a
bare meeting title as the agenda, or as the minutes when its file is named
as minutes (15 July 2025, where
the agenda is under "Business Paper - Ordinary Council Meeting - ...").
Other forms seen: "Ordinary Council Meeting - 30 August 2022 - Agenda",
"Ordinary Council Meeting - 13 December 2022 - Minutes", "... - Confirmed
Meeting Minutes", "21 November 2023 - Confirmed Minutes", "Signed Minutes -
20 August 2024". The base class strips leading dates and meeting names
before matching, and reads "signed" like "confirmed".

21 April 2020 files its confirmed minutes under a second "Agenda - 21 April
2020" heading. The base class takes a file named as minutes under an agenda
heading as the minutes, when no heading says "Minutes".

Kempsey also has a DocsPublished organisation (``kempsey``), but it holds a
single meeting from March 2024 and is not the source.

One production year is 11 requests: the bare listing, the listing filtered
to that year (12 tagged rows in 2026, 9 of them Council meetings) and a
payload per Council meeting.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class KempseyScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 20 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 20

    list_name = "OC CL Public Meetings"
    papers_by = "heading"
    title_heading_agenda = True
    meeting_types = re.compile(r"\b(?:ordinary|extraordinary)\b", re.IGNORECASE)
    # The busiest year is 22 rows (2023, 2024): one listing page a year.
    page_size = 50
    # The bare page is fetched for its rows anyway (see the docstring), so
    # it is also where the year dropdown is read.
    bare_page_rows = True

    def __init__(self):
        super().__init__(
            "kempsey",
            "NSW",
            "https://www.kempsey.nsw.gov.au"
            "/Your-Council/Council-meetings-forums-catchups/Council-meeting-agendas-minutes",
        )
