import sys
import sqlite3

conn = sqlite3.connect("ook2.db")
conn.row_factory = sqlite3.Row


try:
    cur = conn.cursor()
    row = cur.execute("SELECT version FROM state").fetchone()
    version = row["version"]
except sqlite3.OperationalError:
    version = 0
cur.close()


def migration(number):
    def deco(fn):
        global version
        if number >= version:
            print("Running migration", fn.__name__)
            try:
                cur = conn.cursor()
                fn(cur)
                cur.execute("UPDATE state SET version = ?", (version + 1,))
                conn.commit()
                print("Migration successful")
                version += 1
            except sqlite3.OperationalError as e:
                print("Rolling back migration:", e)
                conn.rollback()
                sys.exit(1)
            cur.close()
    return deco


@migration(0)
def initial(cur):
    cur.execute("""
        CREATE TABLE state (version INTEGER)
        """
    )
    cur.execute("""
        INSERT INTO state (version) VALUES (0)
        """
    )
    cur.execute("""
        CREATE TABLE places
        (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE books
        (
            id INTEGER PRIMARY KEY,
            isbn VARCHAR(13),
            title TEXT,
            authors TEXT,
            publisher TEXT,
            year INTEGER,
            created_at TIMESTAMP DEFAULT (datetime('now')),
            imported_at TIMESTAMP,  -- metadata looked up via ISBN
            borrowed_to VARCHAR(64),
            place_id INTEGER,  -- can be null: not in a place
            FOREIGN KEY(place_id) REFERENCES places(id)
        )
    """)

@migration(1)
def rename_places_to_collections(cur):
    cur.execute("""ALTER TABLE places RENAME TO collections""")

@migration(2)
def rename_place_id_to_collection_id(cur):
    cur.execute("""ALTER TABLE books RENAME COLUMN place_id TO collection_id""")

@migration(3)
def add_sort_key(cur):
    cur.execute("""ALTER TABLE books ADD sort_key TEXT""")
