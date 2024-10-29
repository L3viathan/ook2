import re
import json
import random
from datetime import date, datetime
import isbnlib
from isbnlib.registry import bibformatters

from db import conn

bibjson = bibformatters["json"]

def get_first_isbn_match(isbn):
    for provider in ("goob", "openl", "wiki"):
        try:
            if data := bibjson(isbnlib.meta(isbn, service=provider)):
                break
        except isbnlib.ISBNNotConsistentError:
            continue
    return json.loads(data)

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
    def all(cls, *, order_by="id ASC", offset=0, limit=20):
        cur = conn.cursor()
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM {getattr(cls, "table_name", f"{cls.__name__.lower()}s")}
            ORDER BY {order_by}
            LIMIT {limit}
            OFFSET {offset}
            """
        ).fetchall():
            yield cls(row["id"])

    @classmethod
    def all_lent_out(cls, *, order_by="id ASC", page_no=0, page_size=20):
        cur = conn.cursor()
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM {getattr(cls, "table_name", f"{cls.__name__.lower()}s")}
            WHERE borrowed_to IS NOT NULL
            ORDER BY {order_by}
            LIMIT {page_size}
            OFFSET {page_no * page_size}
            """
        ).fetchall():
            yield cls(row["id"])


class Collection(Model):
    table_name = "collections"
    fields = ("name",)

    def populate(self):
        cur = conn.cursor()
        row = cur.execute(
            """
                SELECT
                    id, name
                FROM collections
                WHERE id = ?
            """,
            (self.id,),
        ).fetchone()
        if not row:
            raise ValueError("No Collection with this ID found")
        self.name = row["name"]

    @classmethod
    def new(cls, name):
        cur = conn.cursor()
        cur.execute("INSERT INTO collections (name) VALUES (?)", (name,))
        conn.commit()
        return cls(cur.lastrowid)

    def rename(self, name):
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE collections
            SET name=?
            WHERE id = ?
            """,
            (name, self.id),
        )
        conn.commit()
        self.name = name

    def __format__(self, fmt):
        if fmt == "heading":
            return f"""<h3
                hx-post="/collections/{self.id}/rename"
                hx-swap="outerHTML"
                hx-trigger="blur delay:500ms"
                hx-target="closest h3"
                hx-vals="javascript: name:htmx.find('h3').innerHTML"
                contenteditable
            >{self.name}</h3>
            """
        else:
            return f"""<a
                class="clickable collection"
                hx-push-url="true"
                href="/collections/{self.id}"
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
        "collection",
    )
    table_name = "books"

    colors = [
        ("#405D72", "#cecece"),
        ("#C4DAD2", "black"),
        ("#B6C4B6", "black"),
        ("#DDDDDD", "#06113C"),
        ("#EEEEEE", "#06113C"),
        ("#D5D5D5", "#091353"),
        ("#87A7B3", "#001F3F"),
        ("#6A9AB0", "#001F3F"),
        ("#B9E5E8", "#0B192C"),
        ("#DFF2EB", "#0B192C"),
        ("#7AB2D3", "#0B192C"),
    ]

    @property
    def style(self):
        bg, fg = Book.colors[int(self.isbn) % len(Book.colors)]
        pad = int(self.isbn) % 10
        if self.borrowed_to:
            return "color: black; background: repeating-linear-gradient(45deg, #ffafaf, #ffafaf 10px, white 10px, white 20px); padding-left: {pad}px; padding-right: {pad}px;"
        return f"color: {fg}; background: {bg}; padding-left: {pad}px; padding-right: {pad}px;"

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
        if row["collection_id"]:
            self.collection = Collection(row["collection_id"])
        else:
            self.collection = None

    @classmethod
    def new_from_isbn(cls, isbn, collection_id=None):
        data = get_first_isbn_match(isbn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO books (isbn, collection_id) VALUES (?, ?)",
            (isbn, collection_id),
        )
        conn.commit()
        book = Book(cur.lastrowid)
        if data:
            book.import_metadata(data)
        return book

    def import_metadata(self, data=None):
        data = data or get_first_isbn_match(self.isbn)
        if data:
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
    def search(cls, q, *, page_size=20, page_no=0, collection_id=None):
        cur = conn.cursor()
        conditions = [
            "UPPER(title) LIKE '%' || ? || '%'"
        ]
        bindings = [q.upper()]
        if collection_id is not None:
            conditions.append("collection_id = ?")
            bindings.append(collection_id)
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
    def all(cls, *, order_by="id ASC", collection_id=None, offset=0, limit=20):
        conditions = ["1=1"]
        values = []
        if collection_id is not None:
            conditions.append("collection_id = ?")
            values.append(collection_id)

        cur = conn.cursor()
        for row in cur.execute(
            f"""
            SELECT
                id
            FROM {getattr(cls, "table_name", f"{cls.__name__.lower()}s")}
            WHERE {" AND ".join(conditions)}
            ORDER BY {order_by}
            LIMIT {limit}
            OFFSET {offset}
            """,
            tuple(values),
        ).fetchall():
            yield cls(row["id"])

    def __format__(self, fmt):
        if fmt == "heading":
            return f"""
            <span
                hx-post="/books/{self.id}/rename"
                hx-swap="outerHTML"
                hx-trigger="blur delay:500ms"
                hx-target="closest h3"
                hx-vals="javascript: title:htmx.find('span').innerHTML"
                contenteditable
            >{self.title}</span>
            """
        elif fmt == "button-group":
            return f"""
            <div role="group">
                {self:import-ui}{self:lend-ui}{self:delete-ui}
            </div>
            """
        elif fmt == "import-ui":
            if self.title:
                return ""
            return f"""<button
                class="secondary"
                hx-post="/books/{self.id}/fetch"
                hx-swap="outerHTML"
            >🔎<span class="hovershow"> Fetch</span></button>"""
        elif fmt == "delete-ui":
            return f"""<button
                class="error"
                hx-confirm="Do you really want to delete {self.title}?"
                hx-delete="/books/{self.id}"
            >🗑<span class="hovershow"> Delete</span></button>"""
        elif fmt == "lend-ui":
            if self.borrowed_to:
                return f"""<button
                    class="secondary"
                    data-tooltip="lent out to {self.borrowed_to}"
                    data-placement="left"
                    hx-confirm="Did {self.borrowed_to} return the book?"
                    hx-post="/books/{self.id}/return"
                    hx-swap="outerHTML"
                >🫶<span class="hovershow"> Return</span></button>"""
            else:
                return f"""<button
                    class="secondary"
                    hx-prompt="Who do you want to lend it to?"
                    hx-post="/books/{self.id}/lend"
                    hx-swap="outerHTML"
                >🫴<span class="hovershow"> Lend</span></button>"""
        elif fmt.startswith("table-row"):
            fields = fmt.partition(":")[-1].split(",")
            parts = ["<tr>"]
            for field in fields:
                if field == "title":
                    parts.append(f"<td>{self:link}</td>")
                else:
                    parts.append(f"<td>{getattr(self, field)}</td>")
            parts.append("</tr>")
            return "".join(parts)
        elif fmt == "spine":
            return f"""<a
                href="/books/{self.id}"
                class="spine"
                style="{self.style}"
            >{self.authors} — {self.title}</a>"""
        elif fmt == "link":
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
            parts.append("<table>")
            parts.append(f"<tr><td><strong>Title</strong></td><td>{self.title}</td></tr>")
            parts.append(f"<tr><td><strong>Authors</strong></td><td>{self.authors}</td></tr>")
            parts.append(f"<tr><td><strong>Collection</strong></td><td>{self.collection}</td></tr>")
            parts.append(f"<tr><td><strong>Publisher</strong></td><td>{self.publisher}</td></tr>")
            parts.append(f"<tr><td><strong>Year</strong></td><td>{self.year}</td></tr>")
            parts.append(f"<tr><td><strong>ISBN</strong></td><td>{self.isbn}</td></tr>")
            parts.append("</table>")
            return "".join(parts)

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

    def delete(self):
        cur = conn.cursor()
        cur.execute("DELETE FROM books WHERE id=?", (self.id,))
        conn.commit()
        self._cache.pop(self.id)

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

    def lend_to(self, borrower):
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE books
            SET borrowed_to=?
            WHERE id=?
            """,
            (borrower, self.id),
        )
        self.borrowed_to = borrower
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
        self.borrowed_to = None
        conn.commit()

    @property
    def location(self):
        if self.borrowed_to:
            return f"<em>lent to {self.borrowed_to}</em>"
        return self.collection
