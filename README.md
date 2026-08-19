# Council Meeting Agenda Scraper

Scrapes Australian council websites to extract meeting agenda information, including meeting dates, times, locations, and PDF download links.

## Usage Modes

### Adapter Mode (Recommended)

The **new recommended way** to use this scraper is in **adapter mode** with JSON output:

```bash
python ./aus_council_scrapers/main.py --adapter --format json
```

This mode:

- Returns structured JSON output to stdout
- Performs read-only scraping (no database writes, no file downloads, no notifications)
- Designed to be ingested by external applications (e.g., a TypeScript backend that owns the database, frontend, and notification system)
- Safe for programmatic consumption and integration into larger systems
- Returns **multiple meetings per council** spanning multiple years (2020 to current year + 2)

Example JSON output:

```json
{
  "format_version": 1,
  "adapter_mode": true,
  "results": [
    {
      "ok": true,
      "council": "yarra",
      "state": "VIC",
      "meetings": [
        {
          "name": "Council Meeting",
          "date": "2026-01-20",
          "time": "19:00:00",
          "webpage_url": "https://...",
          "download_url": "https://...pdf",
          "location": "Council Chambers"
        },
        {
          "name": "Council Meeting",
          "date": "2025-12-16",
          "time": "19:00:00",
          "webpage_url": "https://...",
          "download_url": "https://...pdf",
          "location": "Council Chambers"
        }
      ]
    }
  ]
}
```

**Note:** The scraper returns **multiple meetings per council**, not just the latest one. By default, it fetches meetings from 2020 to the current year + 2 years in the future.

### Legacy Mode

The scraper can still run in **legacy standalone mode** without the adapter flags:

```bash
python ./aus_council_scrapers/main.py
```

This mode provides the original functionality:

- Downloads PDFs and extracts keywords
- Maintains its own SQLite database (`agendas.db`)
- Can send email and Discord notifications (if configured via `.env`)
- Suitable for standalone deployments

## Architecture

This repository is designed to be a **scraping engine** that can be used in two ways:

1. **As a data source** (adapter mode) - Outputs clean JSON for consumption by other systems
2. **As a standalone application** (legacy mode) - Handles the full pipeline including storage and notifications

# Scraper coverage

**[docs/status.md](docs/status.md) shows which councils work**, regenerated
automatically on every merge to `main`.

Coverage is measured from the recorded fixtures rather than tracked by hand,
because hand-maintained counts drifted badly — this section used to claim
per-state totals that no longer matched reality, and `docs/councils.md`
listed councils as "Functioning" whose fixtures held a single meeting and no
minutes.

```bash
poetry run python scripts/scorecard.py          # every council
poetry run python scripts/scorecard.py --gaps   # only what is unfinished
```

`docs/councils.md` lists every council tracked, with its meeting page and
slug.

[Write a Scraper! (Instructions)](#writing-a-scraper)

# Setup

## Development

1. Setup and activate the Python environment of your choosing.

2. Ensure you have `poetry` installed (e.g. with `pip install poetry`).

3. Run `poetry shell` to ensure you've activated the correct virtual env.

4. Run `poetry install` to install dependencies.

Preferred code formatter is [Black](https://github.com/psf/black).

## Testing

`poetry run pytest` will run all the tests, including on any new scrapers added to the `scrapers/` directory. These tests are also run through GitHub actions upon merge request.

# Running the Application

## Command Line Options

```bash
python ./aus_council_scrapers/main.py [OPTIONS]
```

### Core Flags

- `--adapter` - Enable adapter mode (read-only, no side effects)
- `--format {text|json}` - Output format (default: `text`)
  - `text`: Human-readable output with logging
  - `json`: Machine-readable JSON to stdout
- `--council <name>` - Run only the specified council scraper
- `--state <state>` - Run only scrapers for the specified state
- `--years <year1> [year2 ...]` - Filter meetings by specific year(s). Valid range: 2020 to current year + 2
- `--workers <N>` - Number of concurrent workers (default: 6)

### Scraping Behavior

- `--fresh` - Delete existing database and force re-scrape (legacy mode only)
- `--skip-keywords` - Skip keyword extraction from PDFs
- `--skip-pdf` - Skip PDF download entirely
- `--log-level <LEVEL>` - Set logging verbosity (default: `INFO`)

### Examples

**Adapter mode for external consumption:**

```bash
python ./aus_council_scrapers/main.py --adapter --format json
```

**Single council in adapter mode:**

```bash
python ./aus_council_scrapers/main.py --adapter --format json --council yarra
```

**Filter meetings by specific year(s):**

```bash
# Get only 2025 meetings
python ./aus_council_scrapers/main.py --adapter --format json --years 2025

# Get meetings from 2024 and 2025
python ./aus_council_scrapers/main.py --adapter --format json --years 2024 2025
```

**Legacy standalone mode (all features):**

```bash
python ./aus_council_scrapers/main.py
```

**Legacy mode for a specific state:**

```bash
python ./aus_council_scrapers/main.py --state vic
```

**Quick test without PDF processing:**

```bash
python ./aus_council_scrapers/main.py --skip-pdf --council melbourne
```

A list of councils and their strings can be found in `docs/councils.md`.

## Configuration (.env) - Legacy Mode Only

Environment configuration is only required when running in **legacy standalone mode**. Adapter mode does not use these settings.

### Email Notifications (Legacy)

To enable email notifications in legacy mode:

1. Copy `.env.example` to `.env`
2. Set `GMAIL_FUNCTIONALITY=1`
3. Add your Gmail credentials (may require an [App-specific password](https://support.google.com/accounts/answer/185833))
4. Set `GMAIL_ACCOUNT_RECEIVE` to the recipient email address

### Discord Notifications (Legacy)

To enable Discord notifications in legacy mode, configure:

- `DISCORD_TOKEN` - Your Discord bot token
- `DISCORD_CHANNEL_ID` - Target channel ID
- `DISCORD_GROUP_TAG` - Optional group mention tag

Full Discord setup instructions: `docs/discord.md`

### File Persistence (Legacy)

- `SAVE_FILES=1` - Keep downloaded PDFs and extracted text files (default: delete after processing)

# Writing a scraper

Australia has many, many councils! As such, we need many, many scrapers!

**[AGENTS.md](AGENTS.md) is the guide** — scraper structure, the record and
replay test harness, what a scraper is required to produce, and how to record
fixtures. It is written for both people and AI assistants, and it is kept in
one place so it cannot drift from what the code does. This section used to
repeat it and fell out of date.

The short version:

1. Check whether the council runs a platform we already handle. Often it is a
   ten-line subclass rather than a parser:

   ```bash
   poetry run python scripts/detect_platform.py <slug>
   ```

2. Copy `docs/scraper_template.py` into
   `aus_council_scrapers/scrapers/<state>/<council>.py` and work through the
   TODOs. The template is checked by the test suite, so it always matches the
   current API.

3. Import your scraper in the state's `__init__.py`. `@register_scraper` alone
   does nothing — nine scrapers in this repo were written and then never ran
   because this step was missed.

4. Record fixtures and check the result:

   ```bash
   RECORD=<slug> poetry run pytest tests/scraper_test.py -k <slug> -v
   poetry run python scripts/scorecard.py
   ```

   Read the diff in `tests/test-cases/<slug>-result.json` before committing —
   it is the only place the scraper's real output gets reviewed.

A scraper must return a `list[ScraperReturn]` covering **multiple meetings**,
with agendas and minutes on the same record. Returning a single meeting, or an
empty list, means something is wrong.

If a council returns `403`, stop: that is a known issue with a pending
decision, tracked at
[#142](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/issues/142).
Do not work around it.
