#!/usr/bin/env python3
"""
Test the new skip logic for meetings with agenda and minutes.
"""
import sqlite3
import tempfile
import os


def test_skip_logic_agenda_only_first_time():
    """Test that a meeting with only agenda is NOT skipped the first time."""
    from aus_council_scrapers.database import check_meeting_fully_scraped

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmpfile:
        db_path = tmpfile.name

    try:
        # Create a fresh database
        conn = sqlite3.connect(db_path)
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

        # Check a meeting that hasn't been scraped yet
        is_fully_scraped = check_meeting_fully_scraped(
            agenda_url="https://example.com/agenda.pdf",
            minutes_url=None,
            db_path=db_path,
        )

        assert is_fully_scraped == False, "Should not skip - meeting not yet scraped"
        print("✓ Test passed: New meeting with agenda only is not skipped")

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_skip_logic_agenda_only_second_time():
    """Test that a meeting with only agenda IS skipped the second time."""
    from aus_council_scrapers.database import check_meeting_fully_scraped
    from aus_council_scrapers.base import ScraperReturn
    import datetime

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmpfile:
        db_path = tmpfile.name

    try:
        # Create and populate database
        conn = sqlite3.connect(db_path)
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

        # Insert a record with only agenda
        c.execute(
            """INSERT INTO agendas (
                date_scraped, council, state, meeting_date, meeting_time,
                is_meeting_in_past, webpage_url, agenda_url, minutes_url,
                agenda_wordcount, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.datetime.now().isoformat(),
                "test",
                "NSW",
                "2026-01-15",
                "18:30",
                False,
                "https://example.com/meetings",
                "https://example.com/agenda.pdf",
                None,  # No minutes
                1000,
                b"{}",
            ),
        )
        conn.commit()
        conn.close()

        # Check if the same meeting should be skipped
        is_fully_scraped = check_meeting_fully_scraped(
            agenda_url="https://example.com/agenda.pdf",
            minutes_url=None,
            db_path=db_path,
        )

        assert (
            is_fully_scraped == True
        ), "Should skip - same agenda already scraped without minutes"
        print(
            "✓ Test passed: Same meeting with agenda only is skipped on second scrape"
        )

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_skip_logic_minutes_added_later():
    """Test that when minutes are added later, the meeting is NOT skipped."""
    from aus_council_scrapers.database import check_meeting_fully_scraped
    import datetime

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmpfile:
        db_path = tmpfile.name

    try:
        # Create and populate database
        conn = sqlite3.connect(db_path)
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

        # Insert a record with only agenda (first scrape)
        c.execute(
            """INSERT INTO agendas (
                date_scraped, council, state, meeting_date, meeting_time,
                is_meeting_in_past, webpage_url, agenda_url, minutes_url,
                agenda_wordcount, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.datetime.now().isoformat(),
                "test",
                "NSW",
                "2026-01-15",
                "18:30",
                False,
                "https://example.com/meetings",
                "https://example.com/agenda.pdf",
                None,  # No minutes yet
                1000,
                b"{}",
            ),
        )
        conn.commit()
        conn.close()

        # Now check if we should scrape when minutes have been added
        is_fully_scraped = check_meeting_fully_scraped(
            agenda_url="https://example.com/agenda.pdf",
            minutes_url="https://example.com/minutes.pdf",  # Minutes now available!
            db_path=db_path,
        )

        assert is_fully_scraped == False, "Should NOT skip - minutes are now available"
        print("✓ Test passed: Meeting is re-scraped when minutes are added")

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_skip_logic_both_documents_scraped():
    """Test that a meeting with both agenda and minutes IS skipped the second time."""
    from aus_council_scrapers.database import check_meeting_fully_scraped
    import datetime

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmpfile:
        db_path = tmpfile.name

    try:
        # Create and populate database
        conn = sqlite3.connect(db_path)
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

        # Insert a record with both agenda and minutes
        c.execute(
            """INSERT INTO agendas (
                date_scraped, council, state, meeting_date, meeting_time,
                is_meeting_in_past, webpage_url, agenda_url, minutes_url,
                agenda_wordcount, minutes_wordcount, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.datetime.now().isoformat(),
                "test",
                "NSW",
                "2026-01-15",
                "18:30",
                False,
                "https://example.com/meetings",
                "https://example.com/agenda.pdf",
                "https://example.com/minutes.pdf",
                1000,
                500,
                b"{}",
            ),
        )
        conn.commit()
        conn.close()

        # Check if the same meeting should be skipped
        is_fully_scraped = check_meeting_fully_scraped(
            agenda_url="https://example.com/agenda.pdf",
            minutes_url="https://example.com/minutes.pdf",
            db_path=db_path,
        )

        assert is_fully_scraped == True, "Should skip - both documents already scraped"
        print("✓ Test passed: Meeting with both documents is skipped on second scrape")

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    print("Running skip logic tests...\n")

    test_skip_logic_agenda_only_first_time()
    test_skip_logic_agenda_only_second_time()
    test_skip_logic_minutes_added_later()
    test_skip_logic_both_documents_scraped()

    print("\n✓ All skip logic tests passed!")
