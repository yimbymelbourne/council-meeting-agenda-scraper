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
| `tests/scraper_test.py` | Test harness (recording/playback) |
| `tests/test-cases/` | Cached HTTP responses (`*-replay_data.json`) and expected results (`*-result.json`) |
| `docs/councils.md` | Status table for all councils — update this after fixing a scraper |

---

## Scraper Structure

Every scraper:
- Lives in `aus_council_scrapers/scrapers/<state>/<council>.py`
- Uses `@register_scraper` decorator
- Extends `BaseScraper`
- Implements `def scraper(self) -> list[ScraperReturn]:`
- Must be imported in the state's `__init__.py`

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
| `location` | No | Meeting location |
| `download_url` | No | Deprecated — do not use |

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

Iterate over years: `for year in range(EARLIEST_YEAR, datetime.datetime.now().year + 3):`

---

## How to Fix or Add a Scraper

### Step 1 — Read a Working Scraper First

Before touching anything, read 1–2 functioning scrapers to understand patterns. Good references:

- `aus_council_scrapers/scrapers/vic/bayside.py` — simple requests-based scraper
- `aus_council_scrapers/scrapers/vic/banyule.py` — complex Selenium scraper
- `aus_council_scrapers/scrapers/nsw/inner_west.py` — InfoCouncil-based scraper

### Step 2 — Visit the Council's URL

Check `docs/councils.md` for the council's meeting page URL. Open it and understand its structure before writing code. Look for:
- How meetings are listed (table, list, JS-rendered)
- How to find both agendas and minutes
- Whether meetings span multiple pages or years
- Whether future (upcoming) meetings appear on the same page

### Step 3 — Implement

Write or fix the scraper. Common patterns:
- Parse an HTML listing page with BeautifulSoup
- Match agenda links to minutes links by date or meeting name
- Handle year-by-year pagination where needed

### Step 4 — Run Tests

```bash
poetry run pytest tests/scraper_test.py -k <council_slug> -v
```

If test data exists (`tests/test-cases/<slug>-replay_data.json` and `*-result.json`), the test runs in **playback mode** using cached HTTP responses — no network calls.

If test data does not exist, the test runs **live** and saves new test data files automatically.

**If a scraper changes and the old test data no longer matches:** delete both test data files and re-run to record fresh data:

```bash
rm tests/test-cases/<slug>-result.json tests/test-cases/<slug>-replay_data.json
poetry run pytest tests/scraper_test.py -k <council_slug> -v
```

Then commit the new test data files.

### Step 5 — Update councils.md

After fixing or adding a scraper, update `docs/councils.md` to reflect the current status. The columns are:

- **Agenda Scraper**: `Functioning` / `Broken` / `Not Tested`
- **Minutes Scraper**: `Functioning` / `Not Implemented` / `Broken`
- **Multiple Meetings**: `Functioning` / `Not Implemented` / `Timeout` / `N/A`

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
