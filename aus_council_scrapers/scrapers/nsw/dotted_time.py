"""Rewrite InfoCouncil's dotted meeting times with a colon.

Several grids write times with a dot: "5.30pm", "10.30 AM", or a bare
"9.00". The scrapers pass that text through as `time`, and the shared
`ScraperReturn.cleaned_time` reads it with dateutil, which gets both forms
wrong: "5.30pm" comes out as 17:00 (the minutes are dropped) and "9.00" as
midnight. "5:30pm" and "9:00" parse correctly, so the scrapers that meet
dotted times rewrite them before returning.

This belongs in `cleaned_time` itself, where it would fix every council at
once (14 recorded councils have dotted times). That is a shared-module
change; until it lands, this keeps the councils that use it correct. Once it
does, this module can go.
"""

import re

from aus_council_scrapers.base import ScraperReturn

# An hour and minutes joined by a dot. The lookarounds keep it off dates
# ("18.11.26") and longer numbers.
_DOTTED = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{2})(?![\d.])")


def colon_time(time: str | None) -> str | None:
    if not time:
        return time
    return _DOTTED.sub(r"\1:\2", time)


def colon_times(results: list[ScraperReturn]) -> list[ScraperReturn]:
    for record in results:
        record.time = colon_time(record.time)
        # `cleaned_time` caches its first answer; drop any read before the
        # rewrite so it cannot outlive it.
        record._cleaned_time = None
    return results
