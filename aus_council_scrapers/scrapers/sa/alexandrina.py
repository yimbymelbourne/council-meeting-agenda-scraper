"""Alexandrina Council.

An LGA SA Funnelback collection; see `LGASAFunnelbackScraper`. The council
has no page over its whole collection: each body's page is filtered to that
body. Three are read:

- The council's agendas and minutes. Its documents are filed under three
  labels over the years—"Council Agendas and Minutes", "Public Council
  Agendas and Minutes" and "Agendas and Minutes"—all meaning the council.
- The Fleurieu Regional Assessment Panel, the development assessment panel
  Alexandrina shares with Victor Harbor, Yankalilla and Kangaroo Island. Its
  page here is complete from 2020. Victor Harbor's collection carries the
  panel too, but only from 2025 and with gaps (no 21 July 2026 meeting, no
  22 July 2025 minutes), so neither council's copy is dropped: each is the
  panel's papers as that council publishes them, as with the Upper Spencer
  Gulf panel under Port Augusta and Port Pirie.
- The Audit and Risk Committee, the "Audit Committee" until 2023; both
  labels are one body.

Each page is another Selenium request, 20 s after the last (the crawl
delay). The council information sessions (about 20 a year, agenda-only
notices) are on a fourth page and are not read: it would take a production
year past the ~45 s aim. Nor are the advisory groups and regional bodies
listed under Committees.

Two corrections before assembly (see `RelabellingLGASAScraper`):

- Confidential items released later are filed one per item, as "Item
  12.2-20 January 2025-Appointments to the Fleurieu Regional Assessment
  Panel", sometimes under a date of their own. They are never the agenda or
  minutes, and one filed alone made a meeting on 22 January 2025 that never
  happened.
- The minutes of 20 June 2022 are titled "Council Minutes - 20 June 2022 (No
  audio recording available due to technical issues)", and the base class
  drops any title mentioning a recording. The note is cut from the title.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.lgasa import COUNCIL_MEETING
from aus_council_scrapers.scrapers.sa.lgasa_relabel import RelabellingLGASAScraper


@register_scraper
class AlexandrinaScraper(RelabellingLGASAScraper):
    listing_urls = (
        "https://www.alexandrina.sa.gov.au/council/council-meetings/"
        "council-agendas-and-minutes",
        "https://www.alexandrina.sa.gov.au/council/council/committees/"
        "fleurieu-regional-assessment-panel",
        "https://www.alexandrina.sa.gov.au/council/council/committees/auditcomm",
    )

    committee_names = {
        "Public Council Agendas and Minutes": COUNCIL_MEETING,
        "Audit Committee": "Audit and Risk Committee",
    }

    exclude_titles = re.compile(r"^\s*Item\s*\d", re.IGNORECASE)
    title_fixes = ((re.compile(r"\(\s*No audio recording[^)]*\)", re.IGNORECASE), ""),)

    # One production year, measured 20 Oct 2026 from a home IP: 42 s
    # (3 Selenium page loads, two 20 s crawl delays between them). Orders
    # dispatch only (slowest first); see BaseScraper.expected_seconds.
    expected_seconds = 42

    def __init__(self):
        super().__init__("alexandrina", "SA", "https://www.alexandrina.sa.gov.au")
