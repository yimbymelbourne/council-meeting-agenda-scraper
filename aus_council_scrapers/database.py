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
                agenda_wordcount INT,
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
                agenda_wordcount,
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
                ?, -- agenda_wordcount
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
            agenda_wordcount,  # agenda_length
            keywords_json,  # result
            ai_result,  # AI_result
        ),
    )
    conn.commit()
    conn.close()


def check_url(url: str):
    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute("SELECT * FROM agendas WHERE download_url=?", (url,))
    result = c.fetchone()
    conn.close()
    return result
