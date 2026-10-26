"""Central Darling Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

The listing lives at ``/Council/Meetings/2024-Meetings``, but despite the
name it is the whole meetings list (``OC CL Public Meetings``), with a year
filter offering 2018 and 2021–2026. Meeting types are Ordinary,
Extraordinary and Special—all Council meetings, so nothing is allowlisted.
Upcoming meetings are listed with only a public notice and are skipped
until a paper appears.

Papers are one flat "Related Information" list, so ``papers_by =
"link_text"``, and its labels change from year to year:

* 2021–2022: "15 December 2021 Business Paper (Public)", "ADOPTED 15
  December 2021 Minutes".
* 2023: "Agenda-of-Ordinary-Council-Meeting-13.12.2023.pdf" or
  "ORDINARY-COUNCIL-MEETING-BUSINESS-PAPER-25.10.23" beside separate
  "ATTACHMENTS-OF-..." books, which are passed over.
* 2025–2026: the only paper is the business paper with its attachments bound
  in—"Council-Business-Paper-23-June-2026-Attachments.pdf", "18 August 2026
  Ordinary ... Business Paper with attachments"—which is kept as the agenda.
  The base class reads "with attachments" itself; the filename form is
  ``bound_business_paper``, because the same words in another order are
  Bland's separate attachment books. The 23 July 2025 file's first page is
  "ORDINARY COUNCIL MEETING BUSINESS PAPER 23 JULY 2025" (checked 20 October
  2026). Separate books ("25 May 2022 Business Paper Attachments",
  "Business-Paper-Attachments-Public-28052025.pdf") are passed over. The 4 December 2025 agenda is labelled only by its
  InfoCouncil filename, "CO_20251204_AGN_77_AT.pdf".
* 22 March 2023: the agenda is "Ordinary-Council-Meeting-22-March-2023.pdf",
  only the meeting's name, beside "APPROVED-Council-Minutes-..."; with
  ``title_only_agenda`` the base class takes it as the agenda.

Two extraordinary meetings in April 2023 have only their minutes online.

Public notices, financial statements and meeting recordings (YouTube,
SharePoint) share the list and are not papers.

One production year is 8 requests: the listing filtered to that year (7
meetings in 2026) and a payload per meeting.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper

# "Council-Business-Paper-23-June-2026-Attachments.pdf": the business paper,
# then the meeting's date, then "Attachments".
_BOUND_BUSINESS_PAPER = re.compile(
    r"business-paper-\d{1,2}-[a-z]+-\d{4}-attachments\.pdf", re.IGNORECASE
)


@register_scraper
class CentralDarlingScraper(OpenCitiesMeetingsScraper):
    # One production year, measured 20 Oct 2026 from a home IP: 14 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 14

    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    title_only_agenda = True
    bound_business_paper = _BOUND_BUSINESS_PAPER
    # The busiest year is 13 meetings: one listing page a year.
    page_size = 50
    # The year-filtered page offers every year (checked 20 October 2026).
    year_filtered_first_page = True

    def __init__(self):
        super().__init__(
            "central_darling",
            "NSW",
            "https://www.centraldarling.nsw.gov.au/Council/Meetings/2024-Meetings",
        )
