#!/usr/bin/env python3
"""
Migration script to update the database schema to support both agendas and minutes.

This script adds the new columns (agenda_url, minutes_url, minutes_wordcount)
to existing database tables.
"""
import sqlite3
import sys


def migrate_database(db_path: str = "./agendas.db"):
    """Add new columns to support agenda and minutes URLs."""
    print(f"Migrating database: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Check if columns already exist
        c.execute("PRAGMA table_info(agendas)")
        columns = [row[1] for row in c.fetchall()]

        # Add agenda_url if it doesn't exist
        if "agenda_url" not in columns:
            print("Adding agenda_url column...")
            c.execute("ALTER TABLE agendas ADD COLUMN agenda_url TEXT")
            print("✓ Added agenda_url column")
        else:
            print("✓ agenda_url column already exists")

        # Add minutes_url if it doesn't exist
        if "minutes_url" not in columns:
            print("Adding minutes_url column...")
            c.execute("ALTER TABLE agendas ADD COLUMN minutes_url TEXT")
            print("✓ Added minutes_url column")
        else:
            print("✓ minutes_url column already exists")

        # Add minutes_wordcount if it doesn't exist
        if "minutes_wordcount" not in columns:
            print("Adding minutes_wordcount column...")
            c.execute("ALTER TABLE agendas ADD COLUMN minutes_wordcount INT")
            print("✓ Added minutes_wordcount column")
        else:
            print("✓ minutes_wordcount column already exists")

        # Migrate existing download_url values to agenda_url for backward compatibility
        print("\nMigrating existing download_url values to agenda_url...")
        c.execute(
            """
            UPDATE agendas 
            SET agenda_url = download_url 
            WHERE agenda_url IS NULL AND download_url IS NOT NULL
        """
        )
        rows_updated = c.rowcount
        print(f"✓ Migrated {rows_updated} rows")

        conn.commit()
        conn.close()

        print("\n✓ Migration completed successfully!")
        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "./agendas.db"
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)
