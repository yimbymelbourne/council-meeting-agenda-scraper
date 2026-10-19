import datetime
import re

from aus_council_scrapers.base import (
    InfoCouncilScraper,
    ScraperReturn,
    register_scraper,
)

# Yass dates its grid rows "18.11.26": day, month, two-digit year, no time.
# Every row recorded so far pads the day and month; one or two digits are
# accepted in case a row does not.
_YASS_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2}\b")

# InfoCouncil names an extra meeting of a committee "Extra <committee>":
# "Extra Council", "Extra Sustainability Advisory Committee".
_EXTRA = re.compile(r"^Extra\s+")


@register_scraper
class YassValleyScraper(InfoCouncilScraper):
    # The council's Agendas and Minutes page has no documents of its own; it
    # sends readers here. Every body is kept: the grid is one request a year
    # whatever it lists, advisory committees and focus groups included.
    #
    # Asking for a year the grid does not hold (2012, 2027) returns the
    # current year's grid instead. The base class drops rows whose date is not
    # in the year asked for, which only works if the date can be read—see
    # `__init__`.
    tidy_meeting_rows = True

    # Late reports are Yass's supplementary agendas, listed as rows of their
    # own ("Council Late Report", file `..._SUP.PDF`).
    SUPPLEMENTARY_NAME_REGEX = re.compile(
        r"\s*-?\s*\b(?:Supplementary|Late Report|Late Items)\b", re.IGNORECASE
    )

    def __init__(self):
        super().__init__(
            "yass_valley",
            "NSW",
            "https://www.yassvalley.nsw.gov.au",
            "https://yass.infocouncil.biz/",
        )
        # The project's date pattern does not know "18.11.26", so every row
        # came out undated—and an undated row survives the base class's
        # year check, so each fallback year re-emitted the current year's
        # meetings. And its time pattern reads "18.11" out of the same text as
        # 6:11 pm. The grid gives no times at all, so nothing is lost by
        # matching none.
        self.date_regex = _YASS_DATE
        self.time_regex = re.compile(r"(?!)")

    def scraper(self) -> list[ScraperReturn]:
        results = []
        for record in super().scraper():
            # A row whose date this pattern cannot read ("TBC", or a new
            # format) is dropped with a warning rather than failing the whole
            # council. It cannot be kept: undated, it would pass every year's
            # check and be emitted once per year asked for.
            if not record.date:
                self.logger.warning(
                    f"{self.council_name}: dropped an undated grid row "
                    f"({record.name!r}, {record.agenda_url or record.minutes_url})"
                )
                continue
            # Downstream parsing is month-first, which would read "02.09.26"
            # as 9 February. Give it the unambiguous date.
            record.date = (
                datetime.datetime.strptime(record.date, "%d.%m.%y").date().isoformat()
            )
            if record.name:
                record.name = _EXTRA.sub("Extraordinary ", record.name)
            results.append(record)
        return results
