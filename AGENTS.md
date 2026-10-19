# Agent Guide: Council Meeting Agenda Scraper

## What This Project Does

Scrapes Australian council websites for meeting agendas and minutes. The scraper returns structured data (JSON) covering upcoming and past meetings, filterable by year.

Only **adapter mode** is prioritised. Adapter mode returns clean JSON to stdout with no side effects (no DB writes, no file downloads, no notifications).

**Where this runs in production:** the [council-alerts](https://github.com/yimbymelbourne/council-alerts)
repository runs `Ingest councils` nightly at 19:05 UTC, checking out this
repository's default branch and calling
`main.py --adapter --format json`. That is the only scheduled crawl of
council websites — do not add another here. CI in this repository is
offline: tests replay recorded fixtures and touch no council site unless you
re-record with `RECORD=<slug>`.

---

## Where This Runs — read before weighing any fetching change

Live scraping does not happen here. It happens in a **GitHub Action in
another repository**:

[`yimbymelbourne/council-alerts` → `.github/workflows/ingest-councils.yml`](https://github.com/yimbymelbourne/council-alerts/blob/main/.github/workflows/ingest-councils.yml)

That workflow checks this repo out **at `main`, with no pinned ref**, and runs
`aus_council_scrapers/main.py --adapter --format json` through
`packages/scraper-adapter`. Merging to main is therefore deploying: whatever
lands here runs against every council the following night.

Four constraints follow, and a fetching change that ignores any of them
looks fine locally and breaks production:

1. **Headless only, on a browser nobody declared.** `runs-on: ubuntu-latest`,
   no display and no `xvfb`, so anything needing a headed browser is not
   deployable. And unlike CI here — which installs Chrome explicitly with
   `browser-actions/setup-chrome` — that workflow installs no browser at all
   and relies on whatever the runner image happens to ship. It works today
   (`banyule`, `campbelltown`, `darebin`, `melbourne` and `strathfield` all
   drive Selenium in production), but nothing pins it.
2. **One process for every council, and a hard kill.** The adapter is invoked **once** for all councils, and the Node side `SIGKILL`s it at `SCRAPE_TIMEOUT_MS`—**600 s**, both as the workflow's `env:` value and as `ingestCouncils.ts`'s own fallback. A slow scraper does not just fail itself—the kill discards stdout, so the run ends in `Python adapter did not produce valid JSON on stdout` and **nothing at all is persisted, for any council**. The nightly run currently takes around 340 s of that, so treat per-scraper wall time as a scarce shared resource and say what a new scraper costs. main.py now stops itself before the kill (see "What keeps a run inside 600 s" below), but a council that runs past that budget still gets no update that night. Concurrency is `main.py`'s own `--workers` default, now 10: the adapter passes no flag for it, so unlike the fetcher's env vars it cannot be tuned from the other repo at all.
3. **Env vars are the deployment lever, and they live in the other repo.** The adapter spawns Python with `env: {...process.env}`, so anything in that workflow's `env:` block reaches the fetcher—`FETCH_DELAY`, `FETCH_TIMEOUT`, `ADAPTER_BUDGET_S`, `SCRAPE_TIMEOUT_MS`, `RESIDENTIAL_PROXY_URL`, and any future `USER_AGENT`. The corollary: a mechanism that is only configurable by editing this repo cannot be tuned in production without a PR to `council-alerts`, and a default chosen here is what production gets until someone changes that workflow.
4. **Python 3.11 in production**, 3.10 in CI here, `>=3.10,<3.13` in
   `pyproject.toml`.

### What keeps a run inside 600 s

Five mechanisms, all code defaults here, so none needs a change to `council-alerts`:

| Mechanism | Where | What it prevents |
|---|---|---|
| Request timeout, `(10, 60)` s connect/read | `DefaultFetcher.fetch_with_requests` | A server that accepts the connection and then sends nothing. `api.docassembler.com.au` once held a local run for 12+ minutes at 0% CPU. The read timeout bounds the gap between bytes, not the whole download. `FETCH_TIMEOUT` overrides the read half. |
| Selenium page-load timeout, 60 s | `DefaultFetcher.__setup_selenium_driver` | `driver.get` has no limit by default and waits for the load event forever. |
| Per-host throttle shared across the whole process | `DefaultFetcher.__throttle` | Each scraper builds its own fetcher, so the old per-instance throttle spaced one council's requests and nothing spaced a vendor host. About 12 Resolve tenants share `api.resolve.red` and 7 LGA SA councils share one Funnelback host. Now `FETCH_DELAY` is a real per-host limit: councils on one vendor host take turns, and different hosts still run in parallel. `HOST_DELAY_FACTORS` spaces a busy vendor API at a fraction of `FETCH_DELAY`: `api.resolve.red` is at 0.25 (0.5 s), because at the full 2 s its 13 councils alone hit the 480 s budget. |
| Adapter budget, 480 s | `main.py` `_dispatch` | Councils still running (or still queued) when the budget runs out are reported as `ok: false` with `error.type: "Timeout"`. The finished results are written, stdout is flushed, and the process leaves with `os._exit(0)` instead of joining threads it cannot kill. Just before that, `Fetcher.abandon()` SIGTERMs each abandoned scraper's Chrome and chromedriver, because `os._exit` skips Selenium's cleanup and Chrome otherwise outlives the process. `ADAPTER_BUDGET_S` overrides it; keep it well under `SCRAPE_TIMEOUT_MS`. |
| Slowest-first dispatch | `BaseScraper.expected_seconds`, sorted in `_dispatch` | Wall time is set by whichever scraper finishes last. A 100 s scraper submitted after the cheap ones starts late and runs on alone; submitted first, it overlaps with everything else. |

The `--workers` default went from 6 to 10 at the same time, because the shared throttle means more workers add parallelism across hosts without adding load on any one host.

What this means when you write or change a scraper:

- **The budget is a backstop, not an allowance.** A council that times out gets no update that night. The per-scraper aim stays at about 20 requests and 45 s for one production year.
- **Set `expected_seconds`** on the class when one production year measures well above the 5 s default. Use the measured number, not a guess. It only orders dispatch; nothing enforces it.
- **Do not catch `requests.Timeout` and carry on silently.** A timeout now raises where it used to hang. Treat it like any other fetch failure: log a warning, and let the council fail rather than return a quietly short list. `run_scraper` reports a returned `[]` as `ok: true` with 0 meetings, and council-alerts records that as a successful scrape. The shared base classes follow this: `DocsPublishedScraper` raises when its organisation, storage or document lookup fails, and `InfoCouncilScraper` warns per failed year and raises when every requested year failed—which, in a one-year production run, is any failure.
- **Councils on a shared vendor host queue behind each other.** Ten tenants at five requests each is about 100 s of host time at the default `FETCH_DELAY`. Budget for that when adding a tenant to a busy platform. Measure the tenants *together*, not one at a time: each of the 13 Resolve councils measured 6–133 s on its own, but run together at the full 2 s they queued for 281 requests and woollahra and mitcham were cut off at 480 s. A waiting scraper also holds a worker, so the councils behind it in the queue wait too.

**What council-alerts does with the new fields** (checked against `packages/scraper-adapter/src/schema.ts` and `packages/jobs/src/ingestCouncils.ts`):

- A `Timeout` result is an ordinary `ok: false` result. `CouncilResultSchema` needs `council`, `state` and `error.{type,message}` as strings, and `saveCouncilFailure` records it as a failed scrape. The upsert on failure updates only `state`, so the council's stored meetings are left as they were.
- The exit code must be 0. `runPythonAdapter.ts` rejects the whole payload when the exit code is non-zero, even if the JSON is valid.
- Every result also carries `elapsed_s`, the council's own wall time (`null` for a council that never started). The zod objects strip keys they do not declare, so ingest ignores the field today. Nothing else times scrapers in production, so seeing it there needs `ingestCouncils.ts` to log `r.elapsed_s`.
- Every result also carries `egress`—`"direct"` or `"residential"`—so a night when only the proxied councils failed can be read off the output. Ignored by ingest the same way.

To check what production actually did last night:

```bash
gh run list --repo yimbymelbourne/council-alerts --workflow ingest-councils.yml -L 5
gh run view <run-id> --repo yimbymelbourne/council-alerts --log | grep -E "Scraper failed|SIGKILL"
# and, separately, the councils that "succeeded" with nothing:
gh run view <run-id> --repo yimbymelbourne/council-alerts --log | grep "0 meetings"
```

**That run's `okCouncils` count is not a count of working councils.** It counts councils that did not raise, and a scraper returning an empty list does not raise—so `hunters_hill` and `woollahra` sat inside it for months while returning nothing, after both left InfoCouncil. A council *blocked from the runner's IP* used to land there too: `InfoCouncilScraper` logged per-year fetch failures at DEBUG, so `bayside_nsw` returned 76 meetings for 2026 from a home IP and 0 in production. InfoCouncil now raises when every year fails, and `bayside_nsw` goes through the residential proxy (see "Councils that block GitHub's runners"), but any scraper that catches its own fetch errors can still do the same. Always read the per-council meeting counts, never the summary.

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

#### `years_filter` — the one lever that bounds production cost

`main.py` sets `scraper.years_filter` from `--years` **before** calling
`scraper()`, and production always passes a single year (the workflow computes
`YEARS` and the last runs have all been `2026`). It also filters the results
afterwards, so ignoring the attribute is never *wrong* — it is just wasteful,
and the waste is charged against the shared 600 s budget above.

So read it, and use it to decide what to fetch:

```python
def _wanted_years(self) -> set[int]:
    years_filter = getattr(self, "years_filter", None)
    if years_filter:
        return set(years_filter)
    return set(range(EARLIEST_YEAR, clock.current_year() + 3))
```

`getattr` with a default, because the attribute only exists when `--years` was
passed. This matters most for a council whose documents live on a page per
meeting — `yarra`, `ryde` — where the difference is 16 requests a night
instead of 130. For a listing that is newest-first and paged (`ryde`,
`canterbury_bankstown`), also stop paging once a whole page predates the
earliest year you want.

Note the asymmetry it creates, because it is easy to misread: the cassette is
recorded **unfiltered**, so the fixture — and therefore the coverage in
`status.md` — shows the full history, while production only ever asks for the
current year. Both are correct.

---

## How to Fix or Add a Scraper

### Step 1 — Read a Working Scraper First

Before touching anything, read 1–2 functioning scrapers to understand patterns. Good references:

- `aus_council_scrapers/scrapers/nsw/canada_bay.py` — the simplest shape: one
  request, whole history off a single listing page
- `aus_council_scrapers/scrapers/nsw/camden.py` — a page per year, discovered
  from an index
- `aus_council_scrapers/scrapers/vic/yarra.py` — documents only on per-meeting
  pages, so `years_filter` decides what gets fetched
- `aus_council_scrapers/scrapers/vic/banyule.py` — complex Selenium scraper
- `aus_council_scrapers/scrapers/nsw/innerwest.py` — InfoCouncil-based scraper

Not `vic/bayside.py` as a first reference: the council refuses GitHub's runners, so running it live needs `RESIDENTIAL_PROXY_URL` (see "Councils that block GitHub's runners").

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
| `docspublished.com.au` | `DocsPublishedScraper`—needs only the publishing slug; everything else is resolved from `/api/organisation/<slug>` at runtime |
| `OCServiceHandler.axd`, `accordion-list-item-container` | `OpenCitiesMeetingsScraper` (`aus_council_scrapers/opencities.py`)—needs the listing URL, its `dlv_` list name and whether papers are labelled by heading or link text; see `scrapers/vic/kingston.py`. Rows with no `data-cvid`, only a link to a page per meeting, use `detail_pages = True` (`west_torrens`); `page_size` makes a busy year one listing request (`gold_coast`). Each kept meeting costs one request, so cut a council with many committees down with `meeting_types`. `banyule` is OpenCities too but drives the page with Selenium and has not moved to the base class |
| `*.resolve.red`, `Resolve Public`, `boardsync-theme` | `ResolveScraper` (`aus_council_scrapers/resolve.py`)—needs the portal subdomain as `tenant` and a `meeting_types` pattern. Documents are the tokenless `DocPreview.aspx?aoid=` links, which never expire. The agenda is the packet (`&p=1`), because the bare agenda is now an order of business with no reports in it. Each kept meeting costs one detail call to learn which documents exist. A council that moved to Resolve recently sets `resolve_from` and reads its older papers in `other_meetings` |
| `aw_ksearch.js`, `id="searchapi"` | `KsearchScraper` (`aus_council_scrapers/alyka.py`)—Alyka's Kendo search on Kentico. A JSON POST whose filters ride in `SearchParam`/`SearchFilter` headers read from the page's hidden inputs; the record shape differs per council, so parsing stays in the subclass. See `scrapers/wa/stirling.py` |
| `aw_pagetypelisting.js`, `Alyka.MeetingDocument` | `PageTypeListingScraper` (`aus_council_scrapers/alyka.py`)—Alyka's page-type listing on Kentico. Posts `{SI, PR, ...}` to `div#pageTypeListing[data-api]` and parses the `htmlResult` fragment per council. See `scrapers/wa/joondalup.py`. Use `AlykaScraper._each_year` for a per-year loop, so a host that fails every year raises rather than returning `[]` |
| `CouncilMeetings_usercontrol`, `lvMeetings_dpMeetings` | `CouncilConnectScraper` (`aus_council_scrapers/councilconnect.py`)—Market Creations' WA CMS. Needs the site origin; set `inline_documents` when the year listing links the PDFs (`east_fremantle`), otherwise each meeting costs a page request, and `meeting_types` to read only Council meetings when committees would push a year past ~20 requests (`nedlands`). See `scrapers/wa/cottesloe.py` |
| `cf-mitigated: challenge`, `server: cloudflare` | Cloudflare interstitial—needs Selenium, no header will get past it |

Note that InfoCouncil is not forever: three councils have left the platform
and their old `*.infocouncil.biz` subdomains now 404.

**A domain signature is not proof of absence.** These are matched on vendor
domains and strings, so two things slip past:

- **White-labelled apps.** `yarra_ranges` serves the docspublished app from
  `www.yarraranges.vic.gov.au`, so the `docspublished.com.au` signature never
  appears. What gave it away was the SPA shell loading the *same Angular
  bundle* (`main-RS6B3YTL.js`) as a known docspublished council. Compare bundle
  hashes, and probe `api.docassembler.com.au/api/organisation/<slug>` with
  candidate slugs — it returns the org record or an empty body.
- **Vendor names in the footer.** `platforms.py` matches the bare string
  `granicus`, which hits the OpenCities `<meta name="generator">` tag and the
  "Powered by Granicus" footer, since Granicus owns OpenCities. Four councils
  report as `Granicus/Legistar` on that basis with zero Legistar in the page.

Also check the URL in `docs/councils.md` actually *is* the meeting listing.
Several are landing pages that link to it, and detection run against one of
those sees a page with no meetings on it.

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
different thing from the old blanket deferral. Four outcomes, in order:

1. **The council wants a browser-shaped client.** Rare but real—set `user_agent = BROWSER_USER_AGENT` on the scraper class, verified against that council alone. `manningham` is the only current case (200 as a browser, 403 identifying). `scripts/detect_platform.py` reports this as `browser-only`. **Never widen it to the project default**—13 councils are reachable *because* the default identifies us: `ryde`, which had a scraper but was blocked; `blacktown`, `frankston`, `hume`, `kingston`, `maribyrnong`, `melton`, `monash`, `mornington_peninsula` and `stonnington`, which are on `OpenCitiesMeetingsScraper` now; `nillumbik` and `yarra_ranges`, which have scrapers of their own; and `whittlesea`, which has none yet. (`hobsons_bay` answers too, and has a scraper on the same base class.)
2. **A JS challenge**, not a header problem: `cf-mitigated: challenge` (Cloudflare) or `x-amzn-waf-action: challenge` (AWS, e.g. `melbourne`). Needs Selenium. Note the AWS variant answers **202 with an empty body**, not 403, so it never raises `BlockedByWAF`—a scraper built on `fetch_with_requests` there silently finds nothing. Some Cloudflare sites challenge only GitHub's runners and nothing gets past it from there; see the next section.
3. **Refused from GitHub's runners only.** `bayside_vic` is here: 403 as a browser and a reset connection when identifying, from a runner, and a normal page from a home connection. See the next section.
4. **Genuinely refused, from everywhere.** Leave it alone and say so.

Overrides are constrained by `tests/test_user_agent.py`: an override may only
ever be `BROWSER_USER_AGENT`, so there is one string to re-verify rather than a
drift of hand-rolled ones.

When testing any of this, go through `DefaultFetcher` rather than `curl`. Our
fetcher sends a full header set, and some sites challenge a bare request that
the real client passes — `bayside_nsw` looks blocked under `curl -A` and
returns 200 through the fetcher. Probe the endpoint the **scraper** hits, not
the council's homepage: for every InfoCouncil council those are different
hosts, and `burwood.infocouncil.biz` is fine while `burwood.nsw.gov.au` 403s.

### Councils that block GitHub's runners

Production runs on a GitHub-hosted runner, which has an Azure datacentre IP. Some councils refuse that IP whatever the client sends, and serve the same pages to a home connection. Measured from a runner on 19 Oct 2026:

| Council | From a GitHub runner | From a home IP |
|---|---|---|
| `bayside_nsw` (`infoweb.bayside.nsw.gov.au`) | Cloudflare challenge for requests with either User-Agent, Selenium with and without the headless marker, and Cloudflare WARP. shuck passed about 1 page load in 3. | 669 meetings |
| `cardinia` | The same, and shuck passed 0 of 6. | 122 meetings |
| `bayside_vic` | 403 or a reset connection | 132 meetings |

So these councils go through a proxy on a home machine. Each night council-alerts joins a Tailscale tailnet and sets `RESIDENTIAL_PROXY_URL` to a tinyproxy on that machine. The proxy carries HTTPS `CONNECT` only, and only to an allowlist of council hosts. The infrastructure side is in council-alerts [`docs/residential-egress.md`](https://github.com/yimbymelbourne/council-alerts/blob/main/docs/residential-egress.md).

**Opting a scraper in** is one class attribute, like `user_agent`:

```python
egress = "residential"
```

`DefaultFetcher` then sends that scraper's requests through the proxy, and its Chrome too (`--proxy-server`) if it uses Selenium. Scrapers that do not opt in never touch the proxy. It is read from `RESIDENTIAL_PROXY_URL`, never `HTTP(S)_PROXY`, which requests would apply to every council in the process. On the first fetch:

- **Set to a URL:** a 5 s TCP check of the proxy, once per process, then every request goes through it.
- **Set to `direct`:** this machine already has a residential IP, so requests go direct. Use it when recording a cassette from home: `RECORD=cardinia RESIDENTIAL_PROXY_URL=direct pytest tests/scraper_test.py -k Cardinia`.
- **Unset or empty, or the proxy does not answer:** the fetch raises `EgressUnavailable`, which names the council. The adapter reports it as `ok: false` with that error type, so a night with the home machine asleep shows up as those councils failing by name, not as 0 meetings.

Replay ignores all of this: the playback fetcher never makes a request, so tests stay offline and need no env var.

Three rules:

- **Probe from a runner before opting a council in.** A home connection proves nothing about production: `bayside_nsw` returns 669 meetings from a home IP and returned 0 in production. To probe, push a throwaway branch whose only workflow runs `on: push` to that branch, on `ubuntu-latest`, and fetches the scraper's own endpoints through `DefaultFetcher`. Read the log, then delete the branch. The `Production` environment only deploys from `main`, so the probe sees the runner's own IP, which is the point.
- **Every host the scraper requests must be on the proxy's allowlist.** Opting in here is half the change. The other half is a line in tinyproxy's filter on the home machine, described in the council-alerts doc. A host missing from it fails as a refused proxy tunnel.
- **Keep the list short.** These councils fail together whenever the home machine is asleep or offline. The durable fix is for the council to allowlist us: outreach is tracked in #172 (Bayside NSW) and #173 (Cardinia).

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

`-k` matches the **class** name, not the slug — `-k CanadaBay`, not
`-k canada_bay`, which selects nothing and silently records nothing.

`RECORD=1` re-records everything in the selection — avoid it. Cassettes are
per-council, and a blanket re-record pulls other people's in-flight fixture
changes into your branch.

A cassette stores every response body in full, so a scraper that fetches a
page per meeting is expensive on both axes: recording `ryde` takes ~3.5
minutes of throttled requests and the fixture is 26 MB, `yarra` ~4 minutes and
19 MB. That is in line with what is already here (`manningham` is 27 MB), but
it is the cost of the design — if a listing page carries the document links
directly, as Canada Bay's does, one request covers the whole history.

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

**Return every meeting in range, not just the newest one.** The oldest
scrapers here parsed a listing page, took the first entry and returned a
one-element list. That reads as working — no error, one plausible meeting — and
the scorecard is the only thing that ever noticed. `camden`, `canada_bay`,
`canterbury_bankstown`, `ryde` and `yarra` were all built that way; the last of
them was throwing away 29 of the 30 meeting pages it had already fetched. If
you are looking at `find(...)` where the page has many matches, that is the
bug.

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

Set `tidy_meeting_rows = True` on every new InfoCouncil subclass. Without it the venue in the committee cell runs into the meeting name ("Ordinary Council Chambers 82 Brisbane Street ..."), and each supplementary agenda's grid row becomes a meeting of its own with the supplementary paper as its agenda. With it, the venue goes to `location` and supplementary rows (named "Supplementary"/"Late Items", or filed as `_SUP` or `_CHAIRMANS`) fold onto their parent meeting. It is off by default only because turning it on rewrites the output of the scrapers recorded before it existed (`inner_west`, `liverpool`, `cumberland`, `hornsby` and others); the seven WA and QLD councils use it.
