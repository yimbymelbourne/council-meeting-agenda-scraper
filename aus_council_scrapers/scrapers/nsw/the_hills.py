"""The Hills Shire Council—OpenCities, on `OpenCitiesMeetingsScraper`.

One list (``OC CL Public Meetings``) holds Ordinary and Extraordinary Council
meetings and the Development Assessment Unit, from 2021; upcoming meetings
appear on it too. Older meetings (2012–2020) are on separate per-body archive
pages of a different shape and are not read.

Papers are one flat "Related Information" list labelled by link text—
"Ordinary Council Meeting Agenda - 22 September 2026", "... Minutes - ..."—
beside a run of "MAYORAL MINUTE NO. 31, 2026 - ..." files. Those are motions
the mayor moves at the meeting, not its minutes, and the base class's
``\\bminutes\\b`` passes the singular by.

The filter also offers a Local Traffic Committee type. It has no meetings on
the list today, but each listed meeting costs a payload request, so the
allowlist below keeps the list to Council meetings and the Development
Assessment Unit should it start publishing there. With it, one production year
is about 20 requests; the whole history is about 260.
"""

import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.opencities import OpenCitiesMeetingsScraper


@register_scraper
class TheHillsScraper(OpenCitiesMeetingsScraper):
    list_name = "OC CL Public Meetings"
    papers_by = "link_text"
    meeting_types = re.compile(
        r"\b(?:ordinary|extraordinary|council|development assessment)\b",
        re.IGNORECASE,
    )

    def __init__(self):
        super().__init__(
            "the_hills",
            "NSW",
            "https://www.thehills.nsw.gov.au"
            "/Council/Meeting-Agendas-Minutes/Council-Meeting-Agendas-Minutes",
        )
