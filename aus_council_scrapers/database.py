import sqlite3
import datetime
import json
import traceback

from aus_council_scrapers.base import ScraperReturn


def init():
    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS agendas
                (id INTEGER PRIMARY KEY, 
                date_scraped TEXT, 
                council TEXT,
                state TEXT,
                location TEXT,
                meeting_date TEXT,
                meeting_time TEXT,
                is_meeting_in_past BOOL,
                webpage_url TEXT, 
                download_url TEXT,
                agenda_url TEXT,
                minutes_url TEXT,
                agenda_wordcount INT,
                minutes_wordcount INT,
                result BLOB,
                AI_result TEXT,
                error_message TEXT,
                error_traceback TEXT)"""
    )
    conn.commit()
    conn.close()


def insert_error(council_name: str, state: str, exception: Exception):
    now_date = datetime.datetime.now(datetime.timezone.utc).isoformat()

    traceback_lines = traceback.format_exception(
        type(exception),
        value=exception,
        tb=exception.__traceback__,
    )
    formatted_traceback = "".join(traceback_lines)

    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO agendas (
                date_scraped,
                council,
                state,
                error_message,
                error_traceback
            ) 
            VALUES (
                ?, -- date_scraped
                ?, -- council
                ?, -- state
                ?, -- error_message
                ?  -- error_traceback
            )""",
        (
            now_date,  # date_scraped
            council_name,  # council
            state,  # state
            str(exception),  # error_message
            formatted_traceback,  # error_traceback
        ),
    )
    conn.commit()
    conn.close()


def insert_result(
    council_name: str,
    state: str,
    scraper_result: ScraperReturn,
    keywords: dict | None,
    ai_result: str | None = None,
    agenda_wordcount: int | None = None,
    minutes_wordcount: int | None = None,
):
    now_date = datetime.datetime.now(datetime.timezone.utc).isoformat()

    keywords_json = json.dumps(keywords).encode() if keywords else "{}"
    meeting_time = (
        scraper_result.cleaned_time.isoformat() if scraper_result.cleaned_time else None
    )
    meeting_date = scraper_result.cleaned_date.isoformat()

    is_meeting_in_past = scraper_result.is_date_in_past(state)

    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO agendas (
                date_scraped,
                council,
                state,
                meeting_date,
                meeting_time,
                is_meeting_in_past,
                location,
                webpage_url,
                download_url,
                agenda_url,
                minutes_url,
                agenda_wordcount,
                minutes_wordcount,
                result,
                AI_result
            ) 
            VALUES (
                ?, -- date_scraped
                ?, -- council
                ?, -- state
                ?, -- meeting_date
                ?, -- meeting_time
                ?, -- is_meeting_in_past
                ?, -- location
                ?, -- webpage_url
                ?, -- download_url
                ?, -- agenda_url
                ?, -- minutes_url
                ?, -- agenda_wordcount
                ?, -- minutes_wordcount
                ?, -- result (keywords)
                ? -- AI_result
            )""",
        (
            now_date,  # date_scraped
            council_name,  # council
            state,  # state
            meeting_date,  # meeting_date
            meeting_time,  # meeting_time
            is_meeting_in_past,  # is_meeting_in_past
            scraper_result.cleaned_location,  # location
            scraper_result.webpage_url,  # webpage_url
            scraper_result.download_url,  # download_url
            scraper_result.agenda_url,  # agenda_url
            scraper_result.minutes_url,  # minutes_url
            agenda_wordcount,  # agenda_wordcount
            minutes_wordcount,  # minutes_wordcount
            keywords_json,  # result
            ai_result,  # AI_result
        ),
    )
    conn.commit()
    conn.close()


def check_url(url: str):
    """Check if a URL has already been scraped.

    Checks against download_url, agenda_url, and minutes_url columns.
    """
    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """SELECT * FROM agendas 
           WHERE download_url=? OR agenda_url=? OR minutes_url=?""",
        (url, url, url),
    )
    result = c.fetchone()
    conn.close()
    return result


def check_meeting_fully_scraped(
    agenda_url: str | None, minutes_url: str | None, db_path: str = "agendas.db"
) -> bool:
    """Check if a meeting has been fully scraped (both agenda and minutes if both exist).

    Returns True if:
    - Both agenda_url and minutes_url match an existing record (meeting fully scraped)
    - Only agenda exists and it matches an existing record with no minutes expected

    Returns False if:
    - No matching record found
    - Agenda exists but minutes are new/different (need to scrape minutes)
    - Minutes exist but agenda is new/different (should not happen but handle gracefully)

    Args:
        agenda_url: URL of the agenda PDF
        minutes_url: URL of the minutes PDF (None if not available yet)
        db_path: Path to the database file (for testing)

    Returns:
        True if meeting has been fully scraped, False otherwise
    """
    if not agenda_url:
        # No agenda URL means we can't check - should scrape
        return False

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Find records that match the agenda URL
    c.execute(
        """SELECT agenda_url, minutes_url FROM agendas 
           WHERE agenda_url=? OR download_url=?""",
        (agenda_url, agenda_url),
    )
    results = c.fetchall()
    conn.close()

    if not results:
        # No previous record found - need to scrape
        return False

    # Check if any existing record has both documents matching
    for existing_agenda, existing_minutes in results:
        # If current scrape has minutes
        if minutes_url:
            # Check if we've already scraped this exact combination
            if existing_minutes == minutes_url:
                # Both agenda and minutes match - fully scraped
                return True
        else:
            # Current scrape has no minutes yet
            # If the existing record also has no minutes, it's fully scraped
            if not existing_minutes:
                return True
            # If existing record has minutes but we don't, something changed - should scrape

    # No exact match found - need to scrape
    return False
