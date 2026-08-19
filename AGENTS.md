# Agent Guide: Council Meeting Agenda Scraper

## What This Project Does

Scrapes Australian council websites for meeting agendas and minutes. The scraper returns structured data (JSON) covering upcoming and past meetings, filterable by year.

Only **adapter mode** is prioritised. Adapter mode returns clean JSON to stdout with no side effects (no DB writes, no file downloads, no notifications).

---

## What You Will Be Asked To Do

1. **Fix a broken council scraper** — a scraper that returns errors or zero results
2. **Add a new council scraper** — implement scraping for a council not yet in the project

---

## Key Files and Paths

| Path | Purpose |
|------|---------|
| `aus_council_scrapers/base.py` | `BaseScraper`, `ScraperReturn`, `register_scraper`, fetcher classes |
| `aus_council_scrapers/constants.py` | `EARLIEST_YEAR`, regex patterns, timezones |
| `aus_council_scrapers/scrapers/vic/` | Victoria scrapers |
| `aus_council_scrapers/scrapers/nsw/` | NSW scrapers |
| `aus_council_scrapers/clock.py` | `current_year()` / `today()` — use instead of `datetime` |
| `aus_council_scrapers/conformance.py` | What a scraper must produce, and how coverage is measured |
| `tests/scraper_test.py` | Replays each scraper against its cassette |
| `tests/cassette.py` | The record/replay machinery |
| `tests/test_conformance.py` | The gate: invariants that fail the build |
| `tests/known_broken.py` | Strict xfails for scrapers known to be broken |
| `tests/test-cases/` | Cached HTTP responses (`*-replay_data.json`) and expected results (`*-result.json`) |
| `scripts/scorecard.py` | Coverage report derived from the fixtures |
| `docs/scraper_template.py` | Starting point for a new scraper (kept valid by `tests/test_template.py`) |
| `docs/councils.md` | Council list and meeting-page URLs |

---

## Scraper Structure

Every scraper:
- Lives in `aus_council_scrapers/scrapers/<state>/<council>.py`
- Uses `@register_scraper` decorator
- Extends `BaseScraper`
- Implements `def scraper(self) -> list[ScraperReturn]:`
- Must be imported in the state's `__init__.py` — **this step is load-bearing
  and easy to miss.** `@register_scraper` does nothing if the module is never
  imported: nine scrapers in this repo were written, decorated, and then
  forgotten because the import line was omitted. They have never run and have
  never been tested.

```python
from aus_council_scrapers.base import BaseScraper, ScraperReturn, register_scraper

@register_scraper
class ExampleScraper(BaseScraper):
    def __init__(self):
        super().__init__("example_nsw", "NSW", "https://www.example.nsw.gov.au")

    def scraper(self) -> list[ScraperReturn]:
        html = self.fetcher.fetch_with_requests("https://www.example.nsw.gov.au/meetings")
        # parse HTML, return list of ScraperReturn
        return [
            ScraperReturn(
                name="Ordinary Meeting",
                date="12 March 2025",
                time="7:00 PM",
                webpage_url="https://www.example.nsw.gov.au/meetings",
                agenda_url="https://www.example.nsw.gov.au/agenda.pdf",
                minutes_url="https://www.example.nsw.gov.au/minutes.pdf",
                location="Council Chambers",
            )
        ]
```

### ScraperReturn Fields

| Field | Required | Notes |
|-------|----------|-------|
| `name` | No | Meeting type e.g. "Ordinary Meeting" |
| `date` | **Yes** | Any date string — auto-parsed by `dateutil` |
| `time` | No | Any time string — auto-parsed |
| `webpage_url` | **Yes** | Page where the agenda was found |
| `agenda_url` | No | Direct link to agenda PDF |
| `minutes_url` | No | Direct link to minutes PDF |
| `agenda_html_url` | No | Direct link to agenda in HTML format |
| `minutes_html_url` | No | Direct link to minutes in HTML format |
| `location` | No | Meeting location |
| `download_url` | No | Deprecated but still required for backward compatibility — set to `agenda_url or minutes_url` (PDF only, not HTML) |

### Fetching Pages

```python
# For regular HTML pages:
html = self.fetcher.fetch_with_requests(url)

# For JavaScript-rendered pages:
html = self.fetcher.fetch_with_selenium(url)

# For direct Selenium control (forms, clicks, waits):
driver = self.fetcher.get_selenium_driver()
```

### Year Filtering

Scrapers must return meetings from `EARLIEST_YEAR` (currently 2020) up to at least 2 years in the future. Import and use the constant:

```python
from aus_council_scrapers.constants import EARLIEST_YEAR
```

Iterate over years using the project clock, **not** `datetime.now()`:

```python
from aus_council_scrapers import clock
from aus_council_scrapers.constants import EARLIEST_YEAR

for year in range(EARLIEST_YEAR, clock.current_year() + 3):
    ...
```

Replay pins the clock to the date the cassette was recorded. A scraper reading
the real clock starts requesting an unrecorded year every January, and its
fixture fails for a reason nobody caused.

---

## How to Fix or Add a Scraper

### Step 1 — Read a Working Scraper First

Before touching anything, read 1–2 functioning scrapers to understand patterns. Good references:

- `aus_council_scrapers/scrapers/vic/bayside.py` — simple requests-based scraper
- `aus_council_scrapers/scrapers/vic/banyule.py` — complex Selenium scraper
- `aus_council_scrapers/scrapers/nsw/innerwest.py` — InfoCouncil-based scraper

### Step 2 — Visit the Council's URL

Check `docs/councils.md` for the council's meeting page URL. Open it and understand its structure before writing code. Look for:
- How meetings are listed (table, list, JS-rendered)
- How to find both agendas and minutes
- Whether meetings span multiple pages or years
- Whether future (upcoming) meetings appear on the same page

### Step 3 — Check for a known platform before writing a parser

Many councils run the same handful of platforms, and a match turns a day's
work into a ten-line subclass. Fetch the meeting page and look for:

| Signature in the page or URL | Use |
|---|---|
| `*.infocouncil.biz`, `bpsGridPDFLink`, `grdMenu` | `InfoCouncilScraper` |
| `docspublished.com.au` | see `aus_council_scrapers/scrapers/nsw/parramatta.py` |
| `OCServiceHandler.axd`, `accordion-list-item-container` | OpenCities; see `aus_council_scrapers/scrapers/vic/banyule.py` |
| `cf-mitigated: challenge`, `server: cloudflare` | Cloudflare interstitial — needs Selenium, no header will get past it |

Note that InfoCouncil is not forever: three councils have left the platform
and their old `*.infocouncil.biz` subdomains now 404.

### If you get a 403 — stop, do not work around it

A `403` from a council raises `BlockedByWAF`, which is a **deferral, not a
puzzle to solve**. Do not add headers, change the User-Agent locally, add
proxies, or switch to Selenium to get past it.

The cause is known: our default User-Agent is a spoofed browser string, and
13 of 15 blocked councils return `200` as soon as an identifying User-Agent
is sent instead. The fix is a project-wide decision pending at
[issue #142](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/issues/142).

Leave the council alone and say it is blocked pending #142. Councils
currently in this state: `frankston`, `hobsons_bay`, `hume`, `kingston`,
`maribyrnong`, `melton`, `monash`, `mornington_peninsula`, `nillumbik`,
`stonnington`, `whittlesea`, `yarra_ranges`, `blacktown`.

`cardinia` is the exception: it returns a Cloudflare challenge
(`cf-mitigated: challenge`) and stays blocked whatever the User-Agent, so it
genuinely needs Selenium.

When testing this yourself, go through `DefaultFetcher` rather than `curl`.
Our fetcher sends a full browser-shaped header set, and some sites challenge
a bare request that the real client passes — `bayside_nsw` looks blocked
under `curl -A` and returns 200 through the fetcher.

### Step 4 — Implement

Write or fix the scraper. Common patterns:
- Parse an HTML listing page with BeautifulSoup
- Match agenda links to minutes links by date or meeting name
- Handle year-by-year pagination where needed

### Step 5 — Run Tests

```bash
poetry run pytest tests/scraper_test.py -k <council_slug> -v
```

If test data exists (`tests/test-cases/<slug>-replay_data.json` and `*-result.json`), the test runs in **playback mode** using cached HTTP responses — no network calls.

If test data does not exist, the test runs **live** and saves new test data files automatically.

Playback is **strict**. Two things follow from that:

- A URL the scraper requests that is not in the cassette raises `CassetteMiss`
  instead of returning an empty page. If you see one, the scraper is fetching
  something it wasn't fetching when the cassette was cut — decide whether that
  is intended before re-recording.
- The comparison against `<slug>-result.json` is exact. A scraper that returns
  a different number of meetings, or any changed field, fails.

**If a scraper changes and the old test data no longer matches**, re-record it
by slug:

```bash
RECORD=<council_slug> poetry run pytest tests/scraper_test.py -k <council_slug> -v
```

`RECORD=1` re-records everything in the selection — avoid it. Cassettes are
per-council, and a blanket re-record pulls other people's in-flight fixture
changes into your branch.

Read the diff in `<slug>-result.json` before committing. It is the only place
the scraper's actual output gets reviewed, and going from 200 meetings to 3 is
an easy thing to re-record past without noticing.

### Driving a page with Selenium

`self.fetcher.get_selenium_driver()` is recordable, but only through
`execute_script()`, `page_source` and `get()`. `find_element` and friends
return live handles that cannot be serialised and will raise. Use
`self.fetcher.sleep(n)` rather than `time.sleep(n)` to wait for a page to
settle — during playback nothing is loading and `sleep` becomes a no-op.

### Step 6 — Check the scorecard

```bash
poetry run python scripts/scorecard.py        # all councils
poetry run python scripts/scorecard.py --gaps # only what is unfinished
```

This derives coverage from the recorded fixtures — meetings found, years
covered, minutes coverage — and reports each council as `complete`,
`partial` or `broken`. Nothing is stored: the fixtures are the source of
truth, so there is no scorecard file to update or conflict over.

Two categories, treated differently:

- **Invariants** fail the build (`tests/test_conformance.py`): a meeting
  emitted twice, a date that will not parse, a relative URL, no meetings.
  These are defects now, whatever state the scraper is in.
- **Coverage** is reported only. Reaching two years instead of six means
  unfinished, not broken.

A scraper that is genuinely broken goes in `tests/known_broken.py` with a
reason. Those are *strict* xfails — the build fails when one starts passing,
so an entry cannot outlive its fix.

`docs/councils.md` is still maintained by hand and is the place to record a
council's meeting-page URL.

---

## Critical Rules

**Never return zero results.** A scraper that returns an empty list is broken — it should always return at least upcoming meetings or recent past meetings. If the page structure has changed, investigate why rather than silently returning `[]`.

**Always include future meetings.** Councils publish upcoming agendas before the meeting date. Make sure the scraper captures them — a common failure is only fetching the current year when meetings are already scheduled for next year.

**Handle pagination.** Some councils split meetings across multiple pages or require year-based URL parameters. Iterate over all necessary pages rather than only fetching the first.

**Prefer `fetch_with_requests` over Selenium** where the page is plain HTML. Selenium is slower and more fragile — only use it when content is JavaScript-rendered.

---

## Running the Adapter

To test adapter output manually:

```bash
poetry run python ./aus_council_scrapers/main.py --adapter --format json --council <slug>
```

To filter by year:

```bash
poetry run python ./aus_council_scrapers/main.py --adapter --format json --council <slug> --year 2024
```

---

## InfoCouncil Councils

Many NSW councils use the InfoCouncil platform. A base class handles this:

```python
from aus_council_scrapers.base import InfoCouncilScraper

@register_scraper
class ExampleInfoCouncilScraper(InfoCouncilScraper):
    def __init__(self):
        super().__init__("example_nsw", "NSW", "https://example.infocouncil.biz")
```

Check existing NSW scrapers to see if a council uses InfoCouncil before writing custom parsing logic.
