import sqlite3
import datetime
import json

from aus_council_scrapers.base import ScraperReturn


def init():
    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS agendas
                (id INTEGER PRIMARY KEY, 
                date_scraped TEXT, 
                council TEXT,
                location TEXT,
                meeting_date TEXT,
                meeting_time TEXT,
                webpage_url TEXT, 
                download_url TEXT,
                result BLOB,
                AI_result TEXT)"""
    )
    conn.commit()
    conn.close()


def insert(
    council_name: str,
    scraper_result: ScraperReturn,
    keywords: dict | None,
    ai_result: str | None = None,
):
    now_date = datetime.datetime.now(datetime.timezone.utc).isoformat()

    keywords_json = json.dumps(keywords).encode() if keywords else "{}"
    meeting_time = (
        scraper_result.cleaned_time.isoformat() if scraper_result.cleaned_time else None
    )
    meeting_date = scraper_result.cleaned_date.isoformat()

    conn = sqlite3.connect("agendas.db")
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO agendas (
                date_scraped,
                council,
                meeting_date,
                meeting_time,
                location,
                webpage_url,
                download_url,
                result,
                AI_result
            ) 
            VALUES (
                ?, -- date_scraped
                ?, -- council
                ?, -- meeting_date
                ?, -- meeting_time
                ?, -- location
                ?, -- webpage_url
                ?, -- download_url
                ?, -- result (keywords)
                ? -- AI_result
            )""",
        (
            now_date,
            council_name,
            meeting_date,
            meeting_time,
            scraper_result.location,
            scraper_result.webpage_url,
            scraper_result.download_url,
            keywords_json,
            ai_result,
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
