from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.escribe import EScribeScraper

# Logan's own meetings page (logan.qld.gov.au/about-council/mayor-and-councillors/
# committees-and-meetings) links straight out to this portal. Every Council and
# committee meeting from late 2019 is on it, upcoming ones included.
#
# The PDFs are served by FileStream.ashx, which sits behind a Cloudflare JS
# challenge for non-browser clients on the network production runs from, while
# the HTML renditions (Meeting.aspx?...&Agenda=...) answer 200. Both are
# emitted: the PDF in agenda_url/minutes_url as the field contract requires,
# the HTML in *_html_url for anything downstream that cannot pass the
# challenge.
_PORTAL_URL = "https://pub-logancity.escribemeetings.com"


# Logan restructured its four standing committees in June 2026, and eScribe
# renamed the four meeting types in place, so every earlier meeting shows up
# under a name that committee never had. The cover page of each agenda prints
# the name at the time: meeting No. 845 (12-13 May 2026) is the last under the
# old names and No. 846 (9-10 June 2026) the first under the new.
#
# The pairing is eScribe's—which type each old committee's meetings were filed
# under—not a claim that the new committee does the old one's job. Planning
# is the case in point: the City Planning, Economic Development and
# Environment Committee's meetings sit under the type now called "Water,
# Waste and Energy, Natural Areas Committee", while planning business since
# June 2026 goes to the City Shape, Economic Transformation and Transport
# Committee.
_RENAMED_ON = "2026-06-09"
_FORMER_NAMES = {
    "City Shape, Economic Transformation and Transport Committee": (
        _RENAMED_ON,
        "City Infrastructure Committee",
    ),
    "Governance and Transformation Committee": (
        _RENAMED_ON,
        "City Governance Committee",
    ),
    "Thriving Community Committee": (_RENAMED_ON, "City Lifestyle Committee"),
    "Water, Waste and Energy, Natural Areas Committee": (
        _RENAMED_ON,
        "City Planning, Economic Development and Environment Committee",
    ),
}


@register_scraper
class LoganScraper(EScribeScraper):
    former_names = _FORMER_NAMES

    def __init__(self):
        super().__init__("logan", "QLD", _PORTAL_URL)
