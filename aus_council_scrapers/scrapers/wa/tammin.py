import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_small_shires import (
    SmallShireCouncilConnectScraper,
)

_AGENDA = re.compile(r"agenda", re.IGNORECASE)
_MINUTES = re.compile(r"minut", re.IGNORECASE)


@register_scraper
class TamminScraper(SmallShireCouncilConnectScraper):
    """Shire of Tammin—documents on each meeting's own page.

    Council and electors' meetings; the audit committee is skipped by
    heading or type.

    Tammin posts every attachment under the "Agenda" heading, including
    minutes the council receives from other bodies: "SOT BFAC Minutes
    September 2026" is the Bush Fire Advisory Committee's, and names no
    committee for the shared class to catch. The base trusts a label that
    says minutes over the group it sits in, so it took that for the
    meeting's minutes. Here a minutes file under "Agenda" is treated as the
    attachment it is.
    """

    corrected_dates = {
        # The page says 23 September 2026 at 5:00 AM. The agenda's notice of
        # meeting says Wednesday 30 September 2026 at 5:00 pm, and both
        # documents and the recording are filed as 30.09.2026.
        "https://www.tammin.wa.gov.au/council-meetings/ordinary-council-meeting"
        "/ordinary-council-meeting-23-september-2026/329": (
            "2026-09-30",
            "5:00 PM",
            "agenda's notice of meeting",
        ),
    }

    # One production year, measured 20 Oct 2026 from a home IP: 22 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 22

    def _pick_documents(self, links, meeting_name=None, date=None):
        return super()._pick_documents(
            [
                (group, label, url)
                for group, label, url in links
                if not (
                    group
                    and _AGENDA.search(group)
                    and _MINUTES.search(label)
                    and not _AGENDA.search(label)
                )
            ]
        )

    def __init__(self):
        super().__init__("tammin", "WA", "https://www.tammin.wa.gov.au")
