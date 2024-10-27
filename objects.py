import re
import json
from datetime import date, datetime
import isbnlib
from isbnlib.registry import bibformatters

from db import conn

bibjson = bibformatters["json"]

UNSET = object()
class lazy:
    def __init__(self, name):
        self.value = UNSET
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        if getattr(instance, f"_{self.name}", UNSET) is UNSET:
            +instance
        return getattr(instance, f"_{self.name}")

    def __set__(self, instance, value):
        setattr(instance, f"_{self.name}", value)


class Model:
    def __new__(cls, id):
        if id in cls._cache:
            return cls._cache[id]
        obj = super(Model, cls).__new__(cls)
        cls._cache[id] = obj
        obj._populated = False
        return obj

    def __init__(self, id):
        self.id = id

    def __pos__(self):
        if not self._populated:
            self._populated = True
            self.populate()
        return self

    def __repr__(self):
        return f"<{type(self).__name__} id={self.id}{'+' if self._populated else '-'}>"

    def __init_subclass__(cls):
        cls._cache = {}
        for field in cls.fields:
            setattr(cls, field, lazy(field))

    @classmethod
    def all(cls, *, order_by="id ASC", page_no=0, page_size=20):
        cur = conn.cursor()
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM {getattr(cls, "table_name", f"{cls.__name__.lower()}s")}
            ORDER BY {order_by}
            LIMIT {page_size}
            OFFSET {page_no * page_size}
            """
        ).fetchall():
            yield cls(row["id"])


class Place(Model):
    table_name = "places"
    fields = ("name",)

    def populate(self):
        cur = conn.cursor()
        row = cur.execute(
            """
                SELECT
                    id, name
                FROM places
                WHERE id = ?
            """,
            (self.id,),
        ).fetchone()
        if not row:
            raise ValueError("No Place with this ID found")
        self.name = row["name"]

    @classmethod
    def new(cls, name):
        cur = conn.cursor()
        cur.execute("INSERT INTO places (name) VALUES (?)", (name,))
        conn.commit()
        return cls(cur.lastrowid)

    def rename(self, name):
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE places
            SET name=?
            WHERE id = ?
            """,
            (name, self.id),
        )
        conn.commit()
        self.name = name

    def __format__(self, fmt):
        if fmt == "heading":
            return f"""<h2
                hx-post="/places/{self.id}/rename"
                hx-swap="outerHTML"
                hx-trigger="blur delay:500ms"
                hx-target="closest h2"
                hx-vals="javascript: name:htmx.find('h2').innerHTML"
                contenteditable
            >{self.name}</h2>"""
        else:
            return f"""<a
                class="clickable place"
                hx-push-url="true"
                href="/places/{self.id}"
                hx-select="#container"
                hx-target="#container"
                hx-swap="outerHTML"
            ><strong>{self.name}</strong></a>"""

    def __str__(self):
        return f"{self}"


class Book(Model):
    fields = (
        "title",
        "authors",
        "year",
        "publisher",
        "isbn",
        "borrowed_to",
        "created_at",
        "imported_at",
        "place",
    )
    table_name = "books"

    def populate(self):
        cur = conn.cursor()
        row = cur.execute(
            """
                SELECT *
                FROM books
                WHERE id = ?
            """,
            (self.id,),
        ).fetchone()
        if not row:
            raise ValueError("No book with this ID found")
        self.title = row["title"]
        self.authors = row["authors"]
        self.publisher = row["publisher"]
        self.year = row["year"]
        self.isbn = row["isbn"]
        self.created_at = row["created_at"]
        self.imported_at = row["imported_at"]
        self.borrowed_to = row["borrowed_to"]
        if row["place_id"]:
            self.place = Place(row["place_id"])
        else:
            self.place = None

    @classmethod
    def new_from_isbn(cls, isbn, place_id=None):
        data = bibjson(isbnlib.meta(isbn))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO books (isbn, place_id) VALUES (?, ?)",
            (isbn, place_id),
        )
        conn.commit()
        book = Book(cur.lastrowid)
        if data:
            book.import_metadata(data)
        return book

    def import_metadata(self, data=None):
        data = data or bibjson(isbnlib.meta(self.isbn))
        if data:
            data = json.loads(data)
            self.title = data.get("title")
            print(data)
            self.authors = ", ".join(
                sorted(author["name"] for author in data.get("author", [])),
            )
            self.publisher = data.get("publisher")
            self.year = data.get("year")
            self.imported_at = datetime.now()
            self.save()

    @classmethod
    def search(cls, q, *, page_size=20, page_no=0, place_id=None):
        cur = conn.cursor()
        conditions = [
            "UPPER(title) LIKE '%' || ? || '%'"
        ]
        bindings = [q.upper()]
        if place_id is not None:
            conditions.append("place_id = ?")
            bindings.append(place_id)
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM books
            WHERE {" AND ".join(conditions)}
            LIMIT {page_size}
            OFFSET {page_no * page_size}
            """,
            tuple(bindings),
        ).fetchall():
            yield cls(row["id"])

    @classmethod
    def all(cls, *, order_by="id ASC", place_id=None, page_no=0, page_size=20):
        conditions = ["1=1"]
        values = []
        if place_id is not None:
            conditions.append("place_id = ?")
            values.append(place_id)

        cur = conn.cursor()
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM {getattr(cls, "table_name", f"{cls.__name__.lower()}s")}
            WHERE {" AND ".join(conditions)}
            ORDER BY {order_by}
            LIMIT {page_size}
            OFFSET {page_no * page_size}
            """,
            tuple(values),
        ).fetchall():
            yield cls(row["id"])

    def __format__(self, fmt):
        if fmt == "heading":
            return f"""
            <h2>
            <span
                hx-post="/books/{self.id}/rename"
                hx-swap="outerHTML"
                hx-trigger="blur delay:500ms"
                hx-target="closest h2"
                hx-vals="javascript: title:htmx.find('span').innerHTML"
                contenteditable
            >{self.title}</span>
            <div role="group">
                {self:import-ui}
                {self:lend-ui}
            </div>
            </h2>
            """
        elif fmt == "import-ui":
            if self.title:
                return ""
            return f"""<button
                class="secondary"
                hx-post="/books/{self.id}/fetch"
                hx-swap="outerHTML"
            >🔎 Fetch</button>"""
        elif fmt == "lend-ui":
            if self.borrowed_to:
                return f"""<button
                    class="secondary"
                    data-tooltip="borrowed to {self.borrowed_to}"
                    data-placement="left"
                    hx-confirm="Did {self.borrowed_to} return the book?"
                    hx-post="/books/{self.id}/return"
                    hx-swap="outerHTML"
                >🫶 Return</button>"""
            else:
                return f"""<button
                    class="secondary"
                    hx-prompt="Who do you want to lend it to?"
                    hx-post="/books/{self.id}/lend"
                    hx-swap="outerHTML"
                >🫴 Lend</button>"""
        elif fmt == "full":
            return f"""<a
                class="clickable book-link"
                hx-push-url="true"
                hx-select="#container"
                hx-target="#container"
                hx-swap="outerHTML"
                href="/books/{self.id}"
            >
            {self.title}</a>"""
        elif fmt == "details":
            parts = []
            if self.borrowed_to:
                parts.append(f"""<div class="alert warning">
                    Currently lent out to <strong>{self.borrowed_to}</strong>.
                </div>""")
            parts.append(f"<strong>Author:</strong> {self.authors}")
            parts.append(f"<strong>ISBN:</strong> {self.isbn}")
            return "<br>".join(parts)

        else:
            return f"""<a
                class="clickable book-link"
                hx-push-url="true"
                hx-select="#container"
                hx-target="#container"
                hx-swap="outerHTML"
                href="/books/{self.id}">
                {self.title}</a>"""

    def __str__(self):
        return f"{self}"

    def rename(self, title):
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE books
            SET title=?
            WHERE id = ?
            """,
            (title, self.id),
        )
        conn.commit()
        self.title = title

    def save(self):
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE books
            SET title=?, authors=?, publisher=?, year=?, imported_at=?
            WHERE id = ?
            """,
            (
                self.title,
                self.authors,
                self.publisher,
                self.year,
                self.imported_at,
                self.id,
            ),
        )
        conn.commit()

    def get_active_borrow(self):
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT id
            FROM borrows
            WHERE
                book_id = {self.id}
                AND returned_at IS NULL
            """
        ).fetchall()
        if not rows:
            return None
        [row] = rows
        return Borrow(row["id"])

    def lend_to(self, borrower):
        print("attempting lend to", repr(borrower))
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE books
            SET borrowed_to=?
            WHERE id=?
            """,
            (borrower, self.id),
        )
        conn.commit()

    def return_(self):
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE books
            SET borrowed_to=NULL
            WHERE id=?
            """,
            (self.id,),
        )
        conn.commit()
