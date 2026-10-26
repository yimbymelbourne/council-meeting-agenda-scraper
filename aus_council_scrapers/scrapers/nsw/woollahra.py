import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper


@register_scraper
class WoollahraScraper(ResolveScraper):
    # One production year, measured 19 Oct 2026 from a home IP: 32 s.
    # Orders dispatch only (slowest first); see
    # BaseScraper.expected_seconds.
    expected_seconds = 32

    # Woollahra left InfoCouncil for Resolve (#145). Its website still frames
    # the older DevExpress portal at /web/, but the documents and the API are
    # the same tenant.
    tenant = "woollahra"

    # That /web/ portal is the council's public listing, and it shows past
    # meetings the API marks unpublished, each with Agenda and Minutes links
    # that DocPreview serves. They are published as far as a resident can
    # tell, so they are kept: 35 Council meetings—1 in 2021, all 22 of 2022,
    # 11 in 2023, 1 in 2024—and two panel sittings.
    include_unpublished = True

    # Entered under 6 April 2020 9:00 AM, but its name, agenda and minutes
    # all say Saturday 30 May 2020.
    event_dates = {202: "2020-05-30"}

    # The two electronic panel sittings of 11 March 2021 have their papers
    # crossed: both packets are the 12 Greycliffe Avenue agenda, and the Lyne
    # Park Access Road agenda is only event 2597's bare agenda. Of 596
    # Woollahra meetings with both documents, this is the one where the bare
    # agenda is the bigger.
    agenda_documents = {2597: "agenda"}

    # Woollahra lists about 95 events a year across 20-odd bodies, and each
    # one costs a request to learn which documents it has. So this keeps
    # Council and the bodies that decide planning matters: the Environmental
    # Planning Committee (planning proposals, DCPs), the Local Planning Panel
    # and the Application Assessment Panel, which determines DAs under
    # delegation. Left out are the finance, corporate, traffic, arts and
    # public-forum bodies.
    meeting_types = re.compile(
        r"^(Ordinary Council Meeting|Environmental Planning Committee"
        r"|Woollahra Local Planning Panel|Application Assessment Panel)$"
    )

    def __init__(self):
        super().__init__("woollahra", "NSW")

    def _meeting_name(self, event: dict) -> str:
        name = super()._meeting_name(event)
        # The Local Planning Panel usually sits twice on one day: an
        # electronic sitting that determines applications on the papers, and
        # a public one that hears speakers, each with its own agenda. The
        # meeting type does not tell them apart, so without this every panel
        # day would read as one meeting listed twice. Only the electronic
        # sitting is named consistently ("Electronic", "(Electronic)",
        # "(Electronic Meeting)"); the public one is sometimes "(Public)" and
        # sometimes unqualified, so it keeps the plain name.
        if name.endswith("Local Planning Panel") and _ELECTRONIC.search(
            event.get("name") or ""
        ):
            return f"{name} (Electronic)"
        return name


_ELECTRONIC = re.compile(r"\bElectronic\b", re.IGNORECASE)
