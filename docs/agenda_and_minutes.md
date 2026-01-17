# Agenda and Minutes Support

This document describes the changes made to support both agendas and minutes in the council meeting scraper system.

## Overview

The scraper system has been extended to handle both meeting agendas and minutes as separate documents. Previously, the system only tracked a single `download_url` for each meeting. Now it supports:

- **Agenda URLs** (`agenda_url`): Link to the meeting agenda PDF
- **Minutes URLs** (`minutes_url`): Link to the meeting minutes PDF
- **Backward compatibility**: Existing `download_url` field is maintained for legacy scrapers

## Key Changes

### 1. ScraperReturn Dataclass

The `ScraperReturn` dataclass in [base.py](aus_council_scrapers/base.py) now includes:

```python
@dataclass
class ScraperReturn:
    name: Optional[str]
    date: str
    time: Optional[str]
    webpage_url: str
    download_url: str = None  # Deprecated - kept for backward compatibility
    agenda_url: Optional[str] = None
    minutes_url: Optional[str] = None
    location: Optional[str] = None
```

**Validation**: At least one of `agenda_url`, `minutes_url`, or `download_url` must be provided.

### 2. Database Schema

The database schema has been updated to include:

- `agenda_url TEXT`: URL for the agenda PDF
- `minutes_url TEXT`: URL for the minutes PDF
- `minutes_wordcount INT`: Word count for minutes document

**Migration**: Run the migration script to update existing databases:

```bash
python scripts/migrate_database.py
```

Or for a specific database file:

```bash
python scripts/migrate_database.py /path/to/agendas.db
```

### 3. PDF Processing

The system now processes both PDFs when available:

- **`process_pdfs()`**: Main function that handles both agenda and minutes
- **`process_single_pdf()`**: Processes a single PDF (agenda or minutes)
- **`combine_keywords()`**: Merges keyword counts from both documents

Both PDFs are downloaded, processed for keywords, and stored separately in the database.

### 4. Notifications

Email and Discord notifications now mention both documents when available:

**Email format:**

```
The [council] meeting documents for [date] are now available.

Agenda: [url]
Minutes: [url]
```

**Discord format:**

```
@group: New documents for [council] [date]
Agenda: [url]
Minutes: [url]
```

## Writing Scrapers

### New Scraper Pattern

When writing a new scraper, return both URLs when available:

```python
def scraper(self) -> ScraperReturn:
    # ... scraping logic ...

    return ScraperReturn(
        name=name,
        date=date,
        time=time,
        webpage_url=webpage_url,
        agenda_url=agenda_url,      # URL to agenda PDF
        minutes_url=minutes_url,    # URL to minutes PDF (optional)
        download_url=agenda_url,    # For backward compatibility
    )
```

### Backward Compatibility

Existing scrapers that only set `download_url` will continue to work:

```python
# Old style - still works
return ScraperReturn(
    name=name,
    date=date,
    time=time,
    webpage_url=webpage_url,
    download_url=pdf_url,
)
```

The system will process `download_url` as the agenda by default.

### Finding Minutes Links

Common patterns for finding minutes:

```python
# Look for a link with "minutes" in the text
minutes_link = soup.find("a", string=re.compile("minutes", re.IGNORECASE))
if minutes_link and "href" in minutes_link.attrs:
    minutes_url = base_url + minutes_link["href"]

# Or search through siblings of the agenda link
for sibling in agenda_element.find_next_siblings():
    link = sibling.find("a", string=re.compile("minutes", re.IGNORECASE))
    if link:
        minutes_url = base_url + link["href"]
        break

# Or look for a specific CSS class
minutes_link = meeting_row.find("a", class_="minutes-link")
```

## Examples

### Example 1: Council with Both Agenda and Minutes

```python
@register_scraper
class ExampleScraper(BaseScraper):
    def scraper(self) -> ScraperReturn:
        # Fetch meeting page
        soup = BeautifulSoup(self.fetcher.fetch_with_requests(url), "html.parser")

        # Find agenda link
        agenda_link = soup.find("a", string="Agenda")
        agenda_url = self.base_url + agenda_link["href"]

        # Find minutes link
        minutes_link = soup.find("a", string="Minutes")
        minutes_url = self.base_url + minutes_link["href"] if minutes_link else None

        return ScraperReturn(
            name="Council Meeting",
            date="15 January 2026",
            time="18:30",
            webpage_url=url,
            agenda_url=agenda_url,
            minutes_url=minutes_url,
            download_url=agenda_url,  # For backward compatibility
        )
```

### Example 2: Council with Only Agenda

```python
return ScraperReturn(
    name="Council Meeting",
    date="15 January 2026",
    time="18:30",
    webpage_url=url,
    agenda_url=agenda_url,
    minutes_url=None,  # No minutes available yet
    download_url=agenda_url,
)
```

### Example 3: InfoCouncil Sites

The `InfoCouncilScraper` base class automatically looks for both agenda and minutes links:

```python
@register_scraper
class MyCouncilScraper(InfoCouncilScraper):
    def __init__(self):
        super().__init__(
            council="my_council",
            state="NSW",
            base_url="https://www.mycouncil.gov.au",
            infocouncil_url="https://www.mycouncil.gov.au/meetings"
        )
```

## Testing

When testing scrapers, verify:

1. ✓ Both `agenda_url` and `minutes_url` are correctly extracted
2. ✓ URLs are absolute (not relative)
3. ✓ `download_url` is set for backward compatibility
4. ✓ System handles cases where only one document is available
5. ✓ Keyword extraction works for both documents
6. ✓ Database stores both URLs correctly

## Adapter Mode

When running in adapter mode (`--adapter --format json`), the JSON output includes both URLs:

```json
{
  "ok": true,
  "council": "camden",
  "state": "NSW",
  "meeting": {
    "name": "Council Meeting",
    "date": "2026-01-15",
    "time": "18:30:00",
    "webpage_url": "https://...",
    "agenda_url": "https://.../agenda.pdf",
    "minutes_url": "https://.../minutes.pdf",
    "download_url": "https://.../agenda.pdf"
  }
}
```

## Migration Checklist

For maintainers updating the system:

- [x] Update `ScraperReturn` dataclass with new fields
- [x] Update database schema (3 new columns)
- [x] Update PDF processing to handle both documents
- [x] Update keyword combining logic
- [x] Update email notifications
- [x] Update Discord notifications
- [x] Update example scraper (Camden)
- [x] Update InfoCouncilScraper base class
- [x] Create database migration script
- [x] Update documentation

## Future Improvements

Potential enhancements:

1. Add document type indicators in keyword extraction results
2. Support additional document types (e.g., supplementary papers)
3. Track document publication dates separately
4. Add validation to ensure PDF URLs are valid before downloading
5. Support for meetings with multiple agenda/minutes versions
