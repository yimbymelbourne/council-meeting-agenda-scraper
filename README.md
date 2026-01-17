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
      "meeting": {
        "name": "Council Meeting",
        "date": "2026-01-20",
        "time": "19:00:00",
        "webpage_url": "https://...",
        "download_url": "https://...pdf"
      },
      "location": "Council Chambers"
    }
  ]
}
```

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

# List of functioning scrapers

## Melbourne: 13/31

## Sydney: 18/30

Scraper details, including links and current status, can be found [in the docs](https://github.com/yimbymelbourne/council-meeting-agenda-scraper/blob/main/docs/councils.md) (`docs/councils.md`)

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

You can find a full list of active scrapers at `docs/councils.md`. Additionally, you can find a starting file at `docs/scraper_template.py`.

## How scrapers work

Scrapers for each council are contained within the `scrapers/[state]/` directory.

A scraper should be able to reliably find the most recent agenda on a Council's website. Once that link is found, it is checked against an existing database—if the link is new, then the agenda is downloaded, scanned, and a notification can be sent.

In addition to the link, the scraper function should return an object of the following shape, outlined in `base.py`:

```py
@dataclass
class ScraperReturn:
    name: str # The name of the meeting (e.g. City Development Delegated Committee).
    date: str # The date of the meeting (e.g. 2021-08-01).
    time: str # The time of the meeting (e.g. 18:00).
    webpage_url: str # The URL of the webpage where the agenda is found.
    download_url: str # The URL of the PDF of the agenda.
```

**It is not always possible to scrape the date and time of meetings from Council websites. In these cases, these values should be returned as empty strings.**

The `scraper` function is then included within a Scraper class, which extends `BaseScraper.py`.

## Easy scraping

Thanks to the phenomenal work of @catatonicChimp, a lot of the scraping can now be done by extending the BaseScraper class.

### 1. Duplicate the scraper template

For writing a new scraper, you can refer to and duplicate the template: `docs/scraper_template.py`. The Yarra scraper in `scrapers/vic/yarra.py` is a good functional straightforward example.

### 2. Get the agenda page HTML

In the case of most councils, you will will be able to use the `self.fetcher.fetch_with_requests(url)` method to return the agenda page html as output.

For more complex Javascript pages, you may need to use `self.fetcher.fetch_with_selenium(url)`.

For pages requiring interactivity using a headless browser, you may need to write a Selenium script using the driver returned by `self.fetcher.get_selenium_driver()`, and then utilise the [Selenium library](https://www.selenium.dev/documentation/) to navigate the page effectively.

### 3. Use BeautifulSoup to get the agenda details

Load the HTML into BeautifulSoup like this:

```py
soup = BeautifulSoup(output, 'html.parser')
```

And then use the [BeautifulSoup documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) to navigate the HTML and grab the relevant elements and information.

You may also need to use regular expressions (regexes) to parse dates etc.

Luckily, ChatGPT is quite good at both BeautifulSoup and regexes. So it's recommended that you'll save a great deal of time feeding your HTML into ChatGPT, Github Copilot, or the shockingly reliable [Phind.com](https://www.phind.com) and iterating like that.

Once you have got the agenda download link and all other available, scrapeable information, return a ScraperReturn object.

### 4. Add the scraper class to the folder's `__init__.py` file

To register the Scraper, import the scraper in the relevant folder's `__init__.py` file.

As an example, to add the scraper for the Yarra council, open `council_scrapers/scrapers/vic/__init__.py`, and add:

```py
from council_scrapers.scrapers.vic.yarra import YarraScraper
```

### 5. Run tests and save the cached page

Once you have your scraper working locally, run pytest in the root directory (`council-meeting-agenda-scraper/`) and add the cached results to the commit when successful.

This is done to prevent spamming requests to council pages during the development of scrapers.
