import re
from datetime import date, datetime

from db import conn

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
        "author",
        "isbn",
        "created_at",
        "imported_at",
        "data_source",
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
        self.author = row["author"]
        self.isbn = row["isbn"]
        self.created_at = row["created_at"]
        self.imported_at = row["imported_at"]
        self.data_source = row["data_source"]
        if row["place_id"]:
            self.place = Place(row["place_id"])
        else:
            self.place = None

    @classmethod
    def new_from_isbn(cls, isbn, place_id=None):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO books (isbn, place_id) VALUES (?, ?)",
            (isbn, place_id),
        )
        conn.commit()
        return Book(cur.lastrowid)

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
            FROM entities
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
            {self:lend-ui}
            </h2>
            """
        elif fmt == "lend-ui":
            borrow = self.get_active_borrow()
            if borrow:
                return f"""<button
                    class="secondary"
                    data-tooltip="borrowed to {borrow.lender}"
                    data-placement="left"
                    hx-confirm="Did {borrow.lender} return the book?"
                    hx-post="/borrow/{borrow.id}/return"
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
            SET title=?, author=?, imported_at=?
            WHERE id = ?
            """,
            (self.title, self.author, self.imported_at, self.id),
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

    def lend_to(self, lender):
        print("attempting lend to", repr(lender))
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO borrows
            (book_id, lender)
            VALUES
            (?, ?)
            """,
            (self.id, lender),
        )
        conn.commit()


class Borrow(Model):
    table_name = "borrows"
    fields = ("lender", "book", "borrowed_at", "returned_at")

    def populate(self):
        cur = conn.cursor()
        row = cur.execute(
            """
                SELECT
                    *
                FROM borrows
                WHERE id = ?
            """,
            (self.id,),
        ).fetchone()
        if not row:
            raise ValueError("No borrow with this ID found")
        self.borrowed_at = row["borrowed_at"]
        self.returned_at = row["returned_at"]
        self.book = Book(row["book_id"])
        self.lender = row["lender"]

    def return_now(self):
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE borrows
            SET returned_at=?
            WHERE id=?
            """,
            (datetime.now(), self.id),
        )
        conn.commit()