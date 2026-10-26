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
2. **One process for every council, and a hard kill.** The adapter is invoked **once** for all councils, and the Node side `SIGKILL`s it at `SCRAPE_TIMEOUT_MS`—**600 s**, both as the workflow's `env:` value and as `ingestCouncils.ts`'s own fallback. A slow scraper does not just fail itself—the kill discards stdout, so the run ends in `Python adapter did not produce valid JSON on stdout` and **nothing at all is persisted, for any council**. A full one-year run of all 134 registered councils took 211 s at 10 workers from a home IP on 20 Oct 2026. Production, on a GitHub runner, took about 340 s when the registry held about 40 councils, and the full registry has not run there yet, so treat per-scraper wall time as a scarce shared resource and say what a new scraper costs. Wall time is roughly the sum of every council's time divided by the worker count, so every council's cost counts, not just the slowest. main.py now stops itself before the kill (see "What keeps a run inside 600 s" below), but a council that runs past that budget still gets no update that night. Concurrency is `main.py`'s own `--workers` default, now 10: the adapter passes no flag for it, so unlike the fetcher's env vars it cannot be tuned from the other repo at all.
3. **Env vars are the deployment lever, and they live in the other repo.** The adapter spawns Python with `env: {...process.env}`, so anything in that workflow's `env:` block reaches the fetcher—`FETCH_DELAY`, `FETCH_TIMEOUT`, `ADAPTER_BUDGET_S`, `SCRAPE_TIMEOUT_MS`, `RESIDENTIAL_PROXY_URL`, and any future `USER_AGENT`. The corollary: a mechanism that is only configurable by editing this repo cannot be tuned in production without a PR to `council-alerts`, and a default chosen here is what production gets until someone changes that workflow.
4. **Python 3.11 in production**, 3.10 in CI here, `>=3.10,<3.13` in
   `pyproject.toml`.

### What keeps a run inside 600 s

Five mechanisms, all code defaults here, so none needs a change to `council-alerts`:

| Mechanism | Where | What it prevents |
|---|---|---|
| Request timeout, `(10, 60)` s connect/read | `DefaultFetcher.fetch_with_requests` | A server that accepts the connection and then sends nothing. `api.docassembler.com.au` once held a local run for 12+ minutes at 0% CPU. The read timeout bounds the gap between bytes, not the whole download. `FETCH_TIMEOUT` overrides the read half. |
| Selenium page-load timeout, 60 s | `DefaultFetcher.__setup_selenium_driver` | `driver.get` has no limit by default and waits for the load event forever. |
| Per-host throttle shared across the whole process | `DefaultFetcher.__throttle` | Each scraper builds its own fetcher, so the old per-instance throttle spaced one council's requests and nothing spaced a vendor host. Fifty-one Resolve tenants share `api.resolve.red`, and fifteen DocsPublished councils share DocAssembler's hosts. (The LGA SA councils do not: each listing is on the council's own domain.) Now `FETCH_DELAY` is a real per-host limit: councils on one vendor host take turns, and different hosts still run in parallel. `HOST_DELAY_FACTORS` spaces a busy vendor API at a fraction of `FETCH_DELAY`: `api.resolve.red` is at 0.25 (0.5 s), because at the full 2 s the 13 councils it served then hit the 480 s budget on their own. All 22 Resolve councils run together for one year (`--years 2026`) took 221 s wall from a home IP on 20 Oct 2026, all ok; Woollahra (60 meetings, 221 s) is the long pole. Measure a new tenant together with the others, not alone. |
| Adapter budget, 480 s | `main.py` `_dispatch` | Councils still running (or still queued) when the budget runs out are reported as `ok: false` with `error.type: "Timeout"`. The finished results are written, stdout is flushed, and the process leaves with `os._exit(0)` instead of joining threads it cannot kill. Just before that, `Fetcher.abandon()` SIGTERMs each abandoned scraper's Chrome and chromedriver, because `os._exit` skips Selenium's cleanup and Chrome otherwise outlives the process. `ADAPTER_BUDGET_S` overrides it; keep it well under `SCRAPE_TIMEOUT_MS`. |
| Slowest-first dispatch | `BaseScraper.expected_seconds`, sorted in `_dispatch` | Wall time is set by whichever scraper finishes last. A 100 s scraper submitted after the cheap ones starts late and runs on alone; submitted first, it overlaps with everything else. |

The `--workers` default went from 6 to 10 at the same time, because the shared throttle means more workers add parallelism across hosts without adding load on any one host.

What this means when you write or change a scraper:

- **The budget is a backstop, not an allowance.** A council that times out gets no update that night. The per-scraper aim stays at about 20 requests and 45 s for one production year.
- **Set `expected_seconds`** on the class when one production year measures well above the 5 s default. Use the measured number, not a guess. It only orders dispatch; nothing enforces it.
- **Do not catch `requests.Timeout` and carry on silently.** A timeout now raises where it used to hang. Treat it like any other fetch failure: log a warning, and let the council fail rather than return a quietly short list. `run_scraper` reports a returned `[]` as `ok: true` with 0 meetings, and council-alerts records that as a successful scrape. The shared base classes follow this: `DocsPublishedScraper` raises when its organisation, storage or document lookup fails, and `InfoCouncilScraper` warns per failed year and raises when every requested year failed—which, in a one-year production run, is any failure.
- **The Datascape councils are the longest chain.** Manjimup, Towong and Sandstone take turns on one server at 7 s a request, so together they run about 270 s from dispatch (71, 85 and 99 s on their own; 270 s wall for the group with Halls Creek, home IP, 20 Oct 2026, the second and third having waited 85 s and 163 s for their turns). That is more than half the 480 s budget, longer than the whole registry's 211 s home run, and it has not been measured from a GitHub runner. While one runs, the other two hold idle workers. `datascape.py` bounds it: a council that has waited `MAX_TURN_WAIT_SECONDS` (300 s) for its turn fails as a `TimeoutError`, and its requests use a 30 s read timeout, so a stalled page costs about 67 s with its retry rather than 134 s. Adding a fourth council on `lb-dds-mc2.datascape.cloud` would push the last one in line past that limit.
- **Councils on a shared vendor host queue behind each other.** Ten tenants at five requests each is about 100 s of host time at the default `FETCH_DELAY`. Budget for that when adding a tenant to a busy platform. Measure the tenants *together*, not one at a time: each of the 13 Resolve councils of the time measured 6–133 s on its own, but run together at the full 2 s they queued for 281 requests and woollahra and mitcham were cut off at 480 s. A waiting scraper also holds a worker, so the councils behind it in the queue wait too.

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
| `aus_council_scrapers/scrapers/<state>/` | One folder per state and territory: `act`, `nsw`, `nt`, `qld`, `sa`, `tas`, `vic`, `wa` |
| `aus_council_scrapers/resolve.py`, `opencities.py`, `opencities_content.py`, `alyka.py`, `councilconnect.py`, `councilconnect_library.py`, `lgasa.py`, `craft.py`, `moderngov.py`, `escribe.py`, `ionata.py`, `wpfd.py`, `walkerdesigns.py`, `datascape.py` | One base class per shared platform; see the platform table under Step 3. `InfoCouncilScraper` and `DocsPublishedScraper` are in `base.py` |
| `aus_council_scrapers/pdf_dates.py` | A month-only meeting's day read from its PDF's first page; see "Dating a meeting from its PDF" |
| `aus_council_scrapers/meeting_documents.py` | Groups a flat register of individually titled documents into meetings (`cockburn`, `bayswater`) |
| `aus_council_scrapers/platforms.py` | Platform signatures, read by `scripts/detect_platform.py` |
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
| `OCServiceHandler.axd`, `accordion-list-item-container` | `OpenCitiesMeetingsScraper` (`aus_council_scrapers/opencities.py`)—needs the listing URL, its `dlv_` list name and whether papers are labelled by heading or link text; see `scrapers/vic/kingston.py`. Two more `papers_by` modes: `"folder"` where files sit in `div.meeting-folder` folders headed Agenda/Minutes (`lake_macquarie`, `pyrenees`), and `"search"` where the heading names the meeting or date before the word, "General Meeting Agenda 15 September 2026" (`gladstone`, `queenscliffe`). In every mode a "Business Paper" is the agenda and outranks a bare "Agenda" (the NSW councils). Opt-ins for councils that file loosely, each off by default because it infers more: `label_dates_must_match` drops links dated for another meeting (`broken_hill`), `title_only_agenda` and `title_heading_agenda` read a paper or heading named only for the meeting as its agenda (`kempsey`), `bound_business_paper` names a council's own business-paper-with-attachments form (`central_darling`), `related_fills_gaps` takes a missing paper from Related Information (`central_goldfields`), and `bare_page_rows` also reads the unfiltered first page for rows the editors left off every year's page (`gilgandra`, `kempsey`; one more request). Rows with no `data-cvid`, only a link to a page per meeting, use `detail_pages = True` (`west_torrens`); `page_size` makes a busy year one listing request (`gold_coast`). Each kept meeting costs one request, so cut a council with many committees down with `meeting_types`. `banyule` is OpenCities too but drives the page with Selenium and has not moved to the base class |
| OpenCities generator tag but no `data-cvid` rows: year accordions, tables or headed lists of direct `/files/assets/...` PDF links on a content page | `OpenCitiesContentScraper` (`aus_council_scrapers/opencities_content.py`)—needs only `pages`, a `ContentPage` per URL with `holds` saying which years it can carry, so a production year fetches one to three pages. It reads documents, not meetings: each paper is classified from the link text, then the filename, then the accordion heading, and grouped into meetings. A month-only label takes the day from the filename or the meeting's other paper, or is left out and logged—a day is never invented. A page per year is found with `year_index` and `year_page` (a sitemap.xml works as the index, `goondiwindi`); until the end of March a missing page for the new year only warns. `page_headings` dates links outside accordions, `link_label` reads a link by more than its own text (a table row, `narrandera`), `agenda_words` covers "Booklet" (`northern_peninsula_area`), `meeting_words` admits a word the base refuses (`hepburn`'s confidential meetings), and `numbered_files` stops a leading sequence number reading as the day (`mckinlay`). `misfiled` dates or moves a paper whose label and filename are both wrong, each entry checked against the PDF. Set `month_only_fails` where most papers give only their month, so a year with papers but no dated meeting raises instead of returning `[]` (`temora`, `winton`). See `scrapers/qld/livingstone.py` |
| `*.resolve.red`, `Resolve Public`, `boardsync-theme` | `ResolveScraper` (`aus_council_scrapers/resolve.py`)—needs the portal subdomain as `tenant` and a `meeting_types` pattern. Documents are the tokenless `DocPreview.aspx?aoid=` links, which never expire. The agenda is the packet (`&p=1`), because the bare agenda is now an order of business with no reports in it. Each kept meeting costs one detail call to learn which documents exist. A council that moved to Resolve recently sets `resolve_from` and reads its older papers in `other_meetings`; where those are on LGA SA listing pages, subclass `ResolveWithLGASAArchive` (`lgasa.py`) and list them as `archive_listings` (`charles_sturt`); where they are on an OpenCities meetings listing, read it with `OpenCitiesArchive` (`opencities.py`, `burnside`); where they are in a CouncilConnect library, read it with a `CouncilConnectScraper` that borrows the owner's fetcher (`mundaring`) or with `CouncilConnectArchive` (`councilconnect.py`, `alice_springs`, `east_pilbara`; `nannup` does the same after moving to DocsPublished). A body that never moved, such as Charles Sturt's assessment panel, fails the council when its listing fails, since nothing else carries it |
| `aw_ksearch.js`, `id="searchapi"` | `KsearchScraper` (`aus_council_scrapers/alyka.py`)—Alyka's Kendo search on Kentico. A JSON POST whose filters ride in `SearchParam`/`SearchFilter` headers read from the page's hidden inputs; the record shape differs per council, so parsing stays in the subclass. See `scrapers/wa/stirling.py` |
| `aw_pagetypelisting.js`, `Alyka.MeetingDocument` | `PageTypeListingScraper` (`aus_council_scrapers/alyka.py`)—Alyka's page-type listing on Kentico. Posts `{SI, PR, ...}` to `div#pageTypeListing[data-api]` and parses the `htmlResult` fragment per council. See `scrapers/wa/joondalup.py`. Use `AlykaScraper._each_year` for a per-year loop, so a host that fails every year raises rather than returning `[]` |
| `CouncilMeetings_usercontrol`, `lvMeetings_dpMeetings` | `CouncilConnectScraper` (`aus_council_scrapers/councilconnect.py`)—Market Creations' WA CMS. Needs the site origin; set `inline_documents` when the year listing links the PDFs (`east_fremantle`), otherwise each meeting costs a page request, and `meeting_types` to read only Council meetings when committees would push a year past ~20 requests (`nedlands`). Where a site's per-type year pages drop meetings or 404 (`dalwallinu`, `beverley`), subclass `FilteredListingCouncilConnectScraper` (`councilconnect_filtered.py`), which reads the all-types listing and filters it by URL before any meeting page is fetched. Where a type's own year page 404s, add `type_listings = False` to filter the all-types listing instead (`albany`); where papers are linked in the meeting description rather than the documents block, `body_documents = True` (`koorda`). A paper naming a briefing, audit committee or electors' meeting is never taken as another meeting's agenda or minutes. Where the date field's time is an entry stamp ("5:24 PM", "12:00 AM"), set `plausible_times_only` to blank times off the quarter-hour or outside 7 am–8 pm; `canonical_names = ELECTORS_NAMES` gives electors' meetings one name. Fixes checked by reading the documents go in `wrong_documents`, `accepted_documents` (a paper the rules would drop) and `corrections` (`{page url: {date/time/name}}`). `CouncilConnectArchive` reads a module on behalf of a council that has moved platform, skipping meetings on or after the move, and `untimed_before` drops archive times that are a default or an upload stamp (`alice_springs`). See `scrapers/wa/cottesloe.py` |
| `documentcentre-items`, `categories-dropdown`, `/documents/<id>/<slug>` with no meetings module in use | `CouncilConnectDocumentLibraryScraper` (`aus_council_scrapers/councilconnect_library.py`)—CouncilConnect councils that file papers only in the `/documents/` library. Needs the site origin. Folders are found by their label in the index's folder list (slugs are irregular, and next year's folder does not exist until its first paper), so one production year is the index plus that year's agenda and minutes folders. Whether a paper is the agenda or minutes comes from its label, then its folder. The bracketed date beside each label is an upload date and is never the meeting date. A month-only label ("Agenda OCM February 2025") gets a day only from a dated paper of the same meeting, the council's meeting-dates page (`schedule_path`), or a `corrections` entry read off the cover; otherwise it is left out. Recordings' labels are not used: two of fifteen checked were wrong. Two meetings of one type on one day are told apart by a `time` correction. Until the end of March, a run for the current year with no folder for it yet (only last year's) returns `[]` with a warning; any other empty run raises. See `scrapers/wa/kojonup.py` |
| `lgasa-search.lga.sa.gov.au`, `<council>-council-minutes-and-agenda-push`, `lgasa-web.squiz.cloud` | `LGASAFunnelbackScraper` (`aus_council_scrapers/lgasa.py`)—LGA SA's shared Squiz sites (and Derwent Valley, TAS). Needs only `listing_urls`, the council's agendas-and-minutes page. robots.txt disallows the `search.json` API (`/s/` on lgasa-search) and `query=`/facet parameters on the council sites, and sets `Crawl-delay: 20`, so it reads the listing page with only `num_ranks` and `start_rank` added, 20 s apart per host, through Selenium with `strip_headless_user_agent` (Cloudflare). Document URLs are `lgasa-web.squiz.cloud/?a=<assetId>`, which is not behind Cloudflare. Minutes published "& Attachments" are kept as the minutes, and month-titled papers filed on different days are joined. Per-council attributes for councils that file loosely: `body_from_title` when one label holds several bodies (`kangaroo_island`), `title_kinds` for a council's own paper names (`peterborough`'s "Council Report"), `notice_committees` for bodies whose only paper is a notice, and `restate_lone_dates`, which moves a lone paper to the date its title and file name agree on and holds a month-only paper on the 1st until a paper of the same meeting dates it (`franklin_harbour`). The last is opt-in because it would rewrite four earlier cassettes. See `scrapers/sa/port_adelaide_enfield.py`. Where a council files informal gatherings or released confidential papers as council papers, types meeting dates wrong, or has a planning-panel listing that has stopped, subclass `RegionalLGASAScraper` (`lgasa_regional.py`) instead: `skip_titles`, title dates trusted over filed dates within 45 days unless the file name sides with the filed date, numbered same-day sittings paired by start time, `_relabel` for one body filed under two labels, `historic_listings`, and a failed council listing (the first) failing the run (`scrapers/sa/berri_barmera.py`, `grant.py`) |
| `/assets/meetings/`, `/assets/agendas-minutes/`, `table--agendasMinutes`, `accordion--minutes`, `simple.com.au/gov` | `CraftMeetingsModuleScraper` or `CraftArchiveScraper` (`aus_council_scrapers/craft.py`)—SimpleGov's Craft CMS sites in SA. Needs `listing_url` and a row parser; the folder a PDF sits in decides agenda or minutes. The custom date filter takes ISO dates only (DD/MM answers 500), so a year is one paged query. AWS WAF: Selenium unless plain requests are measured to pass (`playford`). See `scrapers/sa/salisbury.py` |
| `ieListMeetings.aspx`, `ieListDocuments.aspx`, `mgWebService.asmx` | `ModernGovScraper` (`aus_council_scrapers/moderngov.py`)—Civica Modern.Gov. Needs the base URL and a committee allowlist. Documents are only on per-meeting pages, so each allowed committee costs one request per meeting. See `scrapers/nsw/sydney.py` |
| `*.escribemeetings.com`, `GetCalendarMeetings` | `EScribeScraper` (`aus_council_scrapers/escribe.py`)—needs only the portal root. One POST per year to `GetCalendarMeetings` returns every meeting with its documents attached, so a production year is one request. PDFs go in `agenda_url`/`minutes_url` and the `Meeting.aspx` HTML renditions in the `*_html_url` fields. eScribe names a meeting after its current meeting type, so set `former_names` if the council renamed committees in place. See `scrapers/qld/logan.py` |
| `name="f_year"` | `IonataMeetingsScraper` (`aus_council_scrapers/ionata.py`)—Ionata's Tasmanian WordPress meetings archive, cards filtered server-side by `f_year` and paged with `a.next`. Needs the listing URL and the card selectors; the card date is reconciled against the title and dated filenames, which outvote it when it is wrong. See `scrapers/tas/clarence.py`. Kingborough's older Ionata theme has no `f_year` and is bespoke |
| `wpfd_root_category_id`, `/download/<cat>/<slug>/<file>/<name>.pdf` | `WPFileDownloadScraper` (`aus_council_scrapers/wpfd.py`)—WordPress WP File Download categories, static HTML. Needs only `listings` (`WPFDListing` url, `default_name`, `archive`); each file's date is voted on from its title, filename and category slug. Month-only meetings are left out unless a subclass overrides `undated_meeting_date` from a published schedule (`scrapers/tas/west_coast.py`). A category the plugin lazy-loads for a wanted year has no links in the page and fails the scrape. See `scrapers/tas/devonport.py` |
| `walkerdesigns.com.au` in the footer, `table-meeting` | `WalkerDesignsMeetingsScraper` (`aus_council_scrapers/walkerdesigns.py`)—the Launceston agency Walker Designs' Craft CMS council sites in northern Tasmania: one static page, a table per year, columns read from each table's header. Needs only `listing_url`; one request covers every year. The column decides what a document is, checked against its title and file name; a row's date is corrected only when two documents agree on another. A wanted year more than 90 days old with no meeting carrying papers raises. See `scrapers/tas/meander_valley.py`. Dorset's site is the same agency's card template and overrides `listing_rows` |
| `cdn-sites.datascape.cloud`, `?item=id:` links, `/repository/libraries/` | `DatascapeMeetingsScraper` (`aus_council_scrapers/datascape.py`)—Datascape's ASP.NET CMS (Manjimup, Towong, Sandstone, Halls Creek). Needs the listing URL and the `category` filter value or a `keep_categories` pattern; one listing per year (`?category=&month=All&year=`) and one request per item. robots.txt sets `Crawl-delay: 7`, which the base class honours, so a production year is 70–140 s, not seconds. Manjimup, Towong and Sandstone resolve to one load balancer, `lb-dds-mc2.datascape.cloud`, which answers 200 with an empty body when one client reads several of its sites at once, so councils naming the same `backend` take turns; a Cloudflare-fronted site sets `backend = None`. Set `items_are_documents` where the council files one item per agenda or minutes rather than per meeting (`halls_creek`). Papers named by month only are dated from other papers on the item and are otherwise left out with a warning; see the module docstring. See `scrapers/wa/manjimup.py` |
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

**Check robots.txt before writing a scraper.** Read `/robots.txt` on every host the scraper will request, and request no path it disallows, even one the council's own page calls from JavaScript. Honour any `Crawl-delay` in it as that host's spacing. The one exception is a documented one: when robots.txt disallows the only route to a council's official public papers, the maintainer has decided to scrape them anyway, and each such council records the exact disallow lines and the date checked in its own module, and says so in `docs/councils.md`. The councils so far: `swan` (21 Oct 2026; its listing API sits under a disallowed `/v1/`), and from 26 Oct 2026 `wollongong` (every route to its papers—the site's search query strings and the Funnelback host's `/s/`—is disallowed), `fraser_coast` and `mount_magnet` (papers on SharePoint, whose robots.txt disallows everything), `moorabool` and `oberon` (the meetings listing itself is disallowed), and `forbes`, `carrathool` and `carnamah` (the listing is allowed but the PDFs sit under a disallowed path, and council-alerts downloads every emitted document). Do not add a council to this list without the same explicit decision. Papers that need a login stay out whatever robots.txt says. Where a WAF challenges a plain request for robots.txt (the AWS WAF's 202 with an empty body, on five of the SA Craft sites), read it through Selenium as the scraper would. A robots.txt that answers 4xx, as Barossa's does even to Selenium, places no restriction (RFC 9309).

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
| `casey` (`/api/meetings?_format=json`) | An empty body where the JSON should be, behind Varnish with no challenge header we recognise. Measured 20 Oct 2026 by running the whole adapter from a runner. | 100 meetings |
| `wollongong` (`wolcc-search.funnelback.squiz.cloud`) | Cloudflare challenge (403 `cf-mitigated: challenge`) for the scraper's `search.json` URL through `DefaultFetcher`, for bare requests, for robots.txt on all three hosts and for six document PDFs. Measured 26 Oct 2026 by a throwaway-branch probe. | 99 meetings |
| 18 regional councils: `balranald`, `blayney`, `buloke`, `cairns`, `eurobodalla`, `flinders_tas`, `glamorgan_spring_bay`, `greater_geelong`, `greater_shepparton`, `halls_creek`, `hawkesbury`, `latrobe_vic`, `launceston`, `manjimup`, `port_stephens`, `sandstone`, `towong`, `warrnambool` | 403 from a firewall, 405 from the Datascape host, a connection timeout, or (Balranald) a Selenium timeout. Measured 20 Oct 2026 by running every state shard once from a runner. | Built and recorded from a home connection |

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

### Servers that omit their intermediate certificate

A council site that opens in a browser but raises `SSLCertVerificationError: unable to get local issuer certificate` from requests is usually sending its leaf certificate without the intermediate. Browsers fetch the missing one from the leaf's AIA "CA Issuers" URL; requests does not. Check with `openssl s_client -connect <host>:443 -servername <host> -showcerts`: one certificate in the chain and "unable to verify the first certificate" confirms it.

The fix is per scraper and never `verify=False`. Fetch the intermediate from that AIA URL, check that it chains to a root in certifi (`openssl verify -CAfile $(python -m certifi) -untrusted <intermediate> <leaf>`) and that its SHA-256 matches Certificate Transparency (crt.sh), and save it as PEM under `aus_council_scrapers/certs/`. Give it a header saying where it came from, when it was fetched, when it expires and its `# SHA-256:` (`tests/test_extra_ca_certs.py` checks that line against the certificate). Then set `extra_ca_certs = ("<file>.pem",)` on the scraper. Its requests then verify against certifi's bundle plus that file, and no other council trusts it. `benalla` is the one case so far; its intermediate expires 2 Nov 2027.

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

### Dating a meeting from its PDF

Some councils label papers by month only ("MEETING 2026 January Business Paper", "October 2026 Minutes") and give the day nowhere on the page. Since 26 Oct 2026 such a meeting may take its day from the paper's own first page ("BUSINESS PAPER ORDINARY MEETING Thursday 22nd January 2026"), through `aus_council_scrapers/pdf_dates.py`:

- `meeting_date_from_pdf(fetcher, url, year, month)` returns the date or None. Only a date in the listing's month and year is accepted. Where the page gives several, it takes the one in the title that a weekday, "held"/"to be held" or a repeat backs, or the only one a weekday confirms; otherwise None, never a guess. `meeting_date_from_papers` tries a meeting's papers in order and stops at the first that answers. `OpenCitiesContentScraper` does this for month-only papers when `pdf_dates = True` (`carpentaria`, `mapoon`).
- `fetcher.fetch_pdf_text(url)` reads the text cheapest first: an HTTP Range request for the first 256 KB (a server that ignores Range is read that far and closed), which holds page one of most Word-made and "fast web view" files; then the whole file, but only up to `full_limit` (8 MB by default), else `PdfTooLarge`. `fetch_bytes(url, max_bytes=None)` is the bytes primitive; `fetch_with_requests` returns `response.text`, which mangles a PDF. Both go through the per-host throttle and the scraper's egress.
- **A cassette records the text, not the file** (`["pdf_text", url, pages, partial]`, plus `full_limit` when it is not the 8 MB default), with whether it was read whole and how many bytes it cost. That keeps a 25 MB business paper to a line of JSON. `fetch_bytes` is recorded base64. Because a non-default limit is in the key, changing a council's `pdf_full_limit` misses the cassette: re-record with `RECORD=<slug>`.
- **A dead link leaves its meeting out; any other fetch error fails the council.** A paper that answers 404 or 410 raises `PdfGone`, which `meeting_date_from_pdf` logs as a warning and treats like an unreadable paper (None). A council page that links a deleted file would otherwise fail the council every night. Timeouts, connection errors and 5xx responses still raise, so a bad night is never mistaken for a short list.

Use it only when nothing on the page gives the day, and only for meetings in `years_filter`: each meeting costs one or two requests and 0.25–25 MB a night. Read the cheapest paper first: small minutes before a business paper whose cover Acrobat put at the end of a 12 MB file (Warren), but the business paper first where its cover is up front and the minutes are scans (Carpentaria). Measured for one production year (2026, home IP, 26 Oct 2026):

| Council | Meetings | PDF reads | Bytes read | Wall time |
|---|---|---|---|---|
| `warren` | 10 | 10 | 2.6 MB | 22 s |
| `coolamon` | 9 | 9 (18 requests: no minutes file is readable from its first bytes) | 21 MB | 41 s |
| `carpentaria` | 10 | 12 | 2.6 MB | 32 s |
| `kowanyama` | 12 | 15 | 4.9 MB | 34 s |
| `mapoon` | 9 | 9 | 5.1 MB | 32 s |

A CDN fetching a file from its origin for the first time can answer a Range request with a 200 and no length (Carpentaria's, 26 Oct 2026); `read_pdf_text` asks once more, and a file still unreadable is left out that night, so Carpentaria's count can vary by one between runs.

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
