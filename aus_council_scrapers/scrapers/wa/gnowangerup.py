import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.scrapers.wa.councilconnect_shires import (
    ShireCouncilConnectScraper,
)

# Since 2024 the shire files a meeting's agenda under "Agenda Attachment" and
# its minutes under "Minutes Attachments", the only groups on the page (25
# March 2026, 28 May 2025). The base never reads an attachment group, so it
# dropped those meetings outright. The groups are read as what they hold; a
# real attachment in them is still caught by its label ("Public AUDIT
# COMMITTEE MINUTES12 March 2025 unconfirmed Attachment").
_PAPERS_AS_ATTACHMENTS = re.compile(
    r"^\s*(agenda|minutes)\s+attachments?\s*$", re.IGNORECASE
)
# "Confrimed Ordinary Council Meeting 24 May 2023": only minutes are
# confirmed, but the label never says "minutes".
_CONFIRMED = re.compile(r"\bconf(?:ir|ri)med\b", re.IGNORECASE)
# "Agenda Report" under the Agenda heading (25 March and 26 August 2020) is
# never the agenda: one is the LEMC minutes attached to Report 11.2, the
# other opens "REPORT 12.2 of AGENDA". Both were read. Every 2020 file is
# named "<ddmmyyyy>-attachmentN.pdf", so the base's preference for an agenda
# whose filename does not say "attach" rules out the real one too, and it
# falls back to the first label with "agenda" in it—on 25 March, this one.
# Filed as the attachment it is, the base drops it.
_AGENDA_REPORT = re.compile(r"^\s*agenda\s+report\s*$", re.IGNORECASE)


@register_scraper
class GnowangerupScraper(ShireCouncilConnectScraper):
    """Shire of Gnowangerup—documents on each meeting's own page.

    Council meetings only. Every meeting costs a request, and a year runs to
    18–30 of them: besides the Council there are the CEO Review and Risk and
    Audit committees, the electors' meeting and, in 2020–2022, a monthly
    "Infrastructure Report Meeting". None is where planning decisions are
    made, and reading them would put a 2020-sized year past 30 requests.

    The site files its Special meetings as `special-meeting`. Its 2020
    agendas are uploaded as "<ddmmyyyy>-attachmentN.pdf" under the Agenda
    heading; they are the agendas (all eight 2020 Ordinary agendas read,
    among them 23 September's "-attachment1" and 12 February's
    "-attachment2"), so the filename is not held against them—the base
    already trusts a document the label calls the agenda.
    """

    meeting_types = {
        "ordinary-council-meeting": "Ordinary Council Meeting",
        "special-meeting": "Special Council Meeting",
    }

    # One production year, measured 20 Oct 2026 from a home IP: 26 s for
    # 13 requests (the type listings, one per Council meeting of the year
    # and the upcoming page). Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 26

    def __init__(self):
        super().__init__("gnowangerup", "WA", "https://www.gnowangerup.wa.gov.au")

    def _fix_document(self, group, label, url):
        group, label, url = super()._fix_document(group, label, url)
        papers = _PAPERS_AS_ATTACHMENTS.match(group or "")
        if papers:
            group = papers.group(1).title()
        if _AGENDA_REPORT.match(label):
            return group, f"{label} (attachment)", url
        if _CONFIRMED.search(label) and not re.search(
            r"agenda|minut", label, re.IGNORECASE
        ):
            label = f"Minutes {label}"
        return group, label, url
