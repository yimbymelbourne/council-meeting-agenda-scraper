"""The kind of meeting a paper's filename names, for small Victorian
OpenCities councils whose listing types every meeting the same way.

Glenelg, Corangamite, Southern Grampians and West Wimmera type some special,
unscheduled and statutory meetings as plain Council or Ordinary meetings in
the listing row. Their paper filenames still say what the meeting was:
"unscheduled-council-meeting-agenda-20-october-2026.pdf" (Glenelg),
"council-meeting-special-24-september-2024.pdf" (Corangamite),
"agenda-statutory-meeting-5-november-2025.pdf" (Southern Grampians). The
listing type is kept wherever it already names a kind; the filename is read
only when it does not.

The filename rather than the payload's opening line, because the opening
line is free text that often says nothing (Corangamite's is "This meeting
will be livestreamed…", West Wimmera's 28 March 2025 says "Council Meeting"
above two "unscheduled-council-meeting-…" files).
"""

import re
from urllib.parse import unquote, urlparse

KIND = re.compile(r"\b(special|unscheduled|statutory)\b", re.IGNORECASE)


def paper_kind(*urls: str | None) -> str | None:
    """The kind one of the paper filenames names—"Special", "Unscheduled" or
    "Statutory", the first paper's word winning—or None."""
    for url in urls:
        if not url:
            continue
        filename = unquote(urlparse(url).path.rsplit("/", 1)[-1])
        match = KIND.search(re.sub(r"[-_.]", " ", filename))
        if match:
            return match.group(1).capitalize()
    return None
