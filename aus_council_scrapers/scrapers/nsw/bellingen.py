import re

from aus_council_scrapers.base import register_scraper
from aus_council_scrapers.resolve import ResolveScraper

# A Public Forum entered under a Council meeting type, which the type filter
# cannot catch.
_FORUM = re.compile(r"\s*(public|open) forum\b", re.IGNORECASE)


@register_scraper
class BellingenScraper(ResolveScraper):
    # Bellingen's record on Resolve starts with the Ordinary meeting of 27
    # May 2020. The meetings before it are on the council's OpenCities
    # "Historic Council meetings" page, and three of them fall inside
    # EARLIEST_YEAR: the Ordinary meetings of 29 January and 26 February
    # 2020 and the Extraordinary meeting of 3 April 2020. They are not read,
    # because robots.txt disallows that page by its exact path
    # (/Your-Council/Council-Meetings-Elected-Members-Councillor-Workshops/
    # Agenda-Minutes-Councillor-Workshops/Historic-Council-meetings, checked
    # 20 Oct 2026).
    tenant = "bellingen"

    # Council meetings only: "Ordinary Council" in its three term variants,
    # and the "Extraordinary Meeting of Council" type used since December
    # 2023. Left out: the Public Forum and the Councillor Information and
    # Briefing Committee, a briefing that decides nothing.
    meeting_types = re.compile(
        r"^(Ordinary Council\b|Extraordinary Meeting of Council$)"
    )

    # The council suffixes the type with its term: "Ordinary Council - Pre
    # 2021", and "Ordinary Council - 2021-2025", which the base class's term
    # strip leaves as "Ordinary Council -". Extraordinary meetings filed under
    # the ordinary type are named "Extraordinary Council" by the base class,
    # so the dedicated type gets that name too.
    meeting_type_names = {
        "Ordinary Council - Pre 2021": "Ordinary Council",
        "Ordinary Council -": "Ordinary Council",
        "Extraordinary Meeting of Council": "Extraordinary Council",
    }

    def __init__(self):
        super().__init__("bellingen", "NSW")

    def _record(self, event, today):
        # Public Forums from January to April 2026 are filed under Ordinary
        # Council. Checked by name before the detail call, so it costs
        # nothing.
        if _FORUM.match(event.get("name") or ""):
            return None
        return super()._record(event, today)
