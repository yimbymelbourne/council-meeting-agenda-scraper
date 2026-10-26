import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.councilconnect import ELECTORS_NAMES, CouncilConnectScraper


@register_scraper
class KoordaScraper(CouncilConnectScraper):
    """Shire of Koorda—papers linked in each meeting page's text.

    Since about 2023 the meeting page has no documents block: its
    description holds "Agenda", "Minutes" and "Attachments" headings, each
    over a link into the site's general file store
    (/Profiles/koorda/Assets/ClientData/...), which robots.txt allows.
    `body_documents` reads those; older pages use the usual block.

    Council and electors' meetings only. Koorda lists eight committees as
    well (audit, grants, awards, works, governance, bush fire, emergency
    management, CEO recruitment), which put its all-types listing at three
    pages a year; the three per-type pages and the Council meetings are ~15
    requests a production year.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-council-meeting": "Special Council Meeting",
        "annual-electors-meeting": "Annual Meeting of Electors",
    }
    body_documents = True
    first_year = 2016
    plausible_times_only = True
    # The 30 August 2021 special meeting is filed under the Ordinary type and
    # headed "Special Meeting of Council".
    canonical_names = ELECTORS_NAMES + (
        (
            re.compile(r"^special meeting of (?:the )?council$", re.IGNORECASE),
            "Special Council Meeting",
        ),
    )

    # The 2020 Ordinary meetings to September say 4:30 PM; each agenda gives
    # notice of a meeting "commencing at 5.00pm", and the minutes say it
    # opened then (checked for 18 February and 16 September).
    corrections = {
        "https://www.koorda.wa.gov.au/council-meetings/ordinary-council-meeting"
        f"/ordinary-council-meeting-{slug}": {"time": "5:00 PM"}
        for slug in (
            "18-february-2020/44",
            "18-march-2020/45",
            "15-april-2020/46",
            "20-may-2020/47",
            "17-june-2020/48",
            "19-august-2020/54",
            "16-september-2020/55",
        )
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s (14
    # requests). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("koorda", "WA", "https://www.koorda.wa.gov.au")
