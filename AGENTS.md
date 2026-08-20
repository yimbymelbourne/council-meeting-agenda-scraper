# Agent Guide: Council Meeting Agenda Scraper

## What This Project Does

Scrapes Australian council websites for meeting agendas and minutes. The scraper returns structured data (JSON) covering upcoming and past meetings, filterable by year.

Only **adapter mode** is prioritised. Adapter mode returns clean JSON to stdout with no side effects (no DB writes, no file downloads, no notifications).

---

## Where This Runs — read before weighing any fetching change

Live scraping does not happen here. It happens in a **GitHub Action in
another repository**:

[`yimbymelbourne/council-alerts` → `.github/workflows/ingest-councils.yml`](https://github.com/yimbymelbourne/council-alerts/blob/main/.github/workflows/ingest-councils.yml)

That workflow checks this repo out **at `main`, with no pinned ref**, and runs
`aus_council_scrapers/main.py --adapter --format json` through
`packages/scraper-adapter`. Merging to main is therefore deploying: whatever
lands here runs against every council the following night.

There is a second, older runner in this repo —
`.github/workflows/run-agenda.yml` — which builds `agendas.db` on a daily
cron. It is not the production path, and it differs in ways that matter
(it installs Chrome via `browser-actions/setup-chrome`; production does not).

Four constraints follow, and a fetching change that ignores any of them
looks fine locally and breaks production:

1. **Headless only.** `runs-on: ubuntu-latest`, no display and no `xvfb`, and
   production installs no browser at all — Selenium gets whatever Chrome the
   runner image ships. Anything that needs a headed browser is not
   deployable as things stand.
2. **One process for every council, and a hard kill.** The adapter is invoked
   **once** for all councils with `--workers 6`, and the Node side
   `SIGKILL`s it at `SCRAPE_TIMEOUT_MS` (default **180 s**, set in the
   workflow's `env:`). A slow scraper does not just fail itself — the kill
   discards stdout, so the run ends in `Python adapter did not produce valid
   JSON on stdout` and **nothing at all is persisted, for any council**. The
   nightly run already exceeds this budget, so treat per-scraper wall time as
   a scarce shared resource and say what a new scraper costs.
3. **Env vars are the deployment lever, and they live in the other repo.**
   The adapter spawns Python with `env: {...process.env}`, so anything in
   that workflow's `env:` block reaches the fetcher — `FETCH_DELAY`,
   `SCRAPE_TIMEOUT_MS`, and any future `USER_AGENT`. The corollary: a
   mechanism that is only configurable by editing this repo cannot be tuned
   in production without a PR to `council-alerts`, and a default chosen here
   is what production gets until someone changes that workflow.
4. **Python 3.11 in production**, 3.10 in `run-agenda.yml`, `>=3.10,<3.13` in
   `pyproject.toml`.

To check what production actually did last night:

```bash
gh run list --repo yimbymelbourne/council-alerts --workflow ingest-councils.yml -L 5
gh run view <run-id> --repo yimbymelbourne/council-alerts --log | grep -E "Scraper failed|SIGKILL"
```

Prefer a code default that is correct unattended over a knob someone has to
set in the other repo. The User-Agent decision is deliberately shaped that
way: the honest default and the per-council overrides are both in code, so
`ingest-councils.yml` needs no change for them to take effect, and
`USER_AGENT` exists only as an escape hatch.

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
| `scripts/detect_platform.py` | Identify a council's platform before writing a parser |
| `docs/status.md` | Which councils work — generated; regenerate when fixtures change |
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

Scrapers should ask for meetings from `EARLIEST_YEAR` (currently 2020) up to
at least 2 years ahead. This is a **fetch bound** — how far back to bother
requesting — not a target a scraper is judged against. Plenty of councils
publish nothing that old; Banyule offers 2017-2026 in its own filter but has
documents only from 2022. Import and use the constant:

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

### How we identify ourselves, and what a 403 means now

Settled in [#142](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/issues/142):
we identify honestly rather than imitating a browser. **Two channels, two
honest strings, and the difference is not an oversight:**

| Channel | User-Agent | Why |
|---|---|---|
| `fetch_with_requests` | `IDENTIFYING_USER_AGENT` — `aus-council-scrapers/0.1 (+repo URL)` | We are a script; saying so unblocks 13 councils |
| Selenium | Chrome's own string, untouched | We really are Chrome, so its string is already true |

Do **not** "align" these by sending the identifying string to Chrome. It is
measured: it gains nothing on any council and loses `melbourne`, whose
CloudFront rules 403 anything not browser-shaped.

Headless Chrome puts `HeadlessChrome` in that string, and some WAFs reject the
token alone. Stripping it is opt-in per scraper
(`strip_headless_user_agent = True`, currently `melbourne` only) because it is
**not** a free win: it is the difference between 0 and 224 meetings for
melbourne and between 73 and 10 for `banyule`, whose year-filter postbacks
stop working. Verify either flag by running the scraper both ways and
comparing meetings returned — reachability proves nothing here, since banyule
loads its listing page fine and then fails on the interaction.

**A 403 now means we identified ourselves and were refused anyway**, which is a
different thing from the old blanket deferral. Three outcomes, in order:

1. **The council wants a browser-shaped client.** Rare but real — set
   `user_agent = BROWSER_USER_AGENT` on the scraper class, verified against
   that council alone. `manningham` is the only current case (200 as a
   browser, 403 identifying). `scripts/detect_platform.py` reports this as
   `browser-only`. **Never widen it to the project default** — 13 councils are
   reachable *because* the default identifies us: `ryde`, which had a scraper
   but was blocked, plus `blacktown`, `frankston`, `hume`, `kingston`,
   `maribyrnong`, `melton`, `monash`, `mornington_peninsula`, `nillumbik`,
   `stonnington`, `whittlesea` and `yarra_ranges`, which have none yet.
   (`hobsons_bay` also answers now, with a 404 and a real page — its URL in
   `docs/councils.md` is stale.)
2. **A JS challenge**, not a header problem: `cf-mitigated: challenge`
   (Cloudflare, e.g. `cardinia`) or `x-amzn-waf-action: challenge` (AWS, e.g.
   `melbourne`). Needs Selenium. Note the AWS variant answers **202 with an
   empty body**, not 403, so it never raises `BlockedByWAF` — a scraper built
   on `fetch_with_requests` there silently finds nothing.
3. **Genuinely refused.** Leave it alone and say so. `bayside_vic` is here:
   403 as a browser, connection reset when identifying.

Overrides are constrained by `tests/test_user_agent.py`: an override may only
ever be `BROWSER_USER_AGENT`, so there is one string to re-verify rather than a
drift of hand-rolled ones.

When testing any of this, go through `DefaultFetcher` rather than `curl`. Our
fetcher sends a full header set, and some sites challenge a bare request that
the real client passes — `bayside_nsw` looks blocked under `curl -A` and
returns 200 through the fetcher. Probe the endpoint the **scraper** hits, not
the council's homepage: for every InfoCouncil council those are different
hosts, and `burwood.infocouncil.biz` is fine while `burwood.nsw.gov.au` 403s.

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

[docs/status.md](docs/status.md) holds the same thing as a committed table —
read that if you just want to know which councils work.

It is generated, never hand-edited. **If your change alters any fixture, you
must regenerate it or CI fails:**

```bash
poetry run python scripts/scorecard.py --markdown > docs/status.md
```

The command derives coverage from the recorded fixtures — meetings found, years
covered, minutes coverage — and reports each council as `complete`,
`partial` or `broken`. Nothing is stored: the fixtures are the source of
truth, so there is no scorecard file to update or conflict over.

Two categories, treated differently:

- **Invariants** fail the build (`tests/test_conformance.py`): a meeting
  emitted twice, a date that will not parse, a relative URL, no meetings.
  These are defects now, whatever state the scraper is in.
- **Coverage** is reported only. A scraper is `complete` when it returns
  several meetings across at least 3 years, including the current year, with
  minutes on past meetings. How far back its history reaches is reported but
  does not count against it — that is usually the council's choice, not the
  scraper's.

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
