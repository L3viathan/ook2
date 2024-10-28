import os
import base64
import functools
from datetime import datetime
from types import CoroutineType

import isbnlib
from sanic import Sanic, HTTPResponse, html, file, redirect

import objects as O


PAGE_SIZE = 20
app = Sanic("ook2")
CORRECT_AUTH = os.environ["OOK_CREDS"]

def D(multival_dict):
    return {key: val[0] for key, val in multival_dict.items()}


@app.on_request
async def extract_auth(request):
    cookie = request.cookies.get("ook_auth")
    if cookie == CORRECT_AUTH:
        request.ctx.authenticated = True
    else:
        request.ctx.authenticated = False


def authenticated(route):
    @functools.wraps(route)
    async def wrapper(request, *args, **kwargs):
        if not request.ctx.authenticated:
            return HTTPResponse(
                body="401 Unauthorized",
                status=401,
            )
        else:
            print("user was authenticated, letting through dangerous route")
        return await route(request, *args, **kwargs)
    return wrapper


@app.get("/login")
async def login(request):
    try:
        auth = request.headers["Authorization"]
        _, _, encoded = auth.partition(" ")
        redirect_url = D(request.args).get("redirect_url", "/")
        if base64.b64decode(encoded).decode() == CORRECT_AUTH:
            response = html(
                """<button
                    class="login"
                    hx-get="/logout"
                    hx-swap="outerHTML"
                >🚪</button>""",
            )
            response.add_cookie(
                "ook_auth",
                CORRECT_AUTH,
                secure=True,
                httponly=True,
                samesite="Strict",
                max_age=60*60*24*365,  # roughly one year
            )
            return response
        else:
            raise ValueError
    except (KeyError, AssertionError, ValueError):
        return HTTPResponse(
            body="401 Unauthorized",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Ook! access"'},
        )


@app.get("/logout")
async def logout(request):
    response = html(
        """<button
            class="login"
            hx-get="/login"
            hx-swap="outerHTML"
        >🔑</button>"""
    )
    response.delete_cookie("ook_auth")
    return response


def pagination(url, page_no, *, more_results=True):
    q = "&" if "?" in url else "?"
    return f"""<br>
        <a
            role="button"
            class="prev"
            href="{url}{q}page={page_no - 1}"
            {"disabled" if page_no == 1 else ""}
        >&lt;</a>
        <a
            class="next"
            role="button"
            href="{url}{q}page={page_no + 1}"
            {"disabled" if not more_results else ""}
        >&gt;</a>
    """


with open("template.html") as f:
    TEMPLATE = f.read().format


def fragment(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        ret = fn(*args, **kwargs)
        if isinstance(ret, CoroutineType):
            ret = await ret
        return html(ret)
    return wrapper


def page(fn):
    @functools.wraps(fn)
    async def wrapper(request, *args, **kwargs):
        ret = fn(request, *args, **kwargs)
        if isinstance(ret, CoroutineType):
            ret = await ret
        if request.ctx.authenticated:
            login_button = """<button
                class="login"
                hx-get="/logout"
                hx-swap="outerHTML"
            >🚪</button>"""
        else:
            login_button = """<button
                class="login"
                hx-get="/login"
                hx-swap="outerHTML"
            >🔑</button>"""
        return html(TEMPLATE(main=ret, login=login_button))
    return wrapper


@app.get("/")
@page
async def index(request):
    return build_table(
        O.Book.all_lent_out(),
    )


@app.get("/places")
@page
async def list_places(request):
    return "<br>".join(
        str(place) for place in O.Place.all()
    ) + ("""<button
        hx-get="/places/new"
        hx-swap="outerHTML"
        class="button-new"
    >New place</button>""" if request.ctx.authenticated else "")


@app.get("/places/new")
@fragment
async def new_place_form(request):
    return """
        <form
            hx-post="/places/new"
            hx-swap="outerHTML"
            hx-encoding="multipart/form-data"
        >
            <input name="name" placeholder="name"></input>
            <button type="submit">»</button>
        </form>
    """


@app.post("/places/new")
@authenticated
@fragment
async def new_place(request):
    form = D(request.form)
    name = form["name"]
    place = O.Place.new(name)
    return f"""
        <button
            hx-get="/places/new"
            hx-swap="outerHTML"
            class="button-new"
        >New place</button>
        {place}
        <br>
    """


def build_table(
    books,
    *,
    isbn_input_url=None,
    base_url=None,
    page_size=PAGE_SIZE,
    page_no=1,
):
    rows = []
    more_results = False
    for i, book in enumerate(books):
        if i == page_size:
            more_results = True
        else:
            rows.append(f"{book:table-row:title,authors,location}")
    if isbn_input_url:
        rows.append(f"""
            <tr><td><input
                type="text"
                name="isbn"
                hx-post="{isbn_input_url}"
                hx-swap="outerHTML"
                hx-target="closest tr"
                placeholder="insert ISBN"
                autofocus
            ></td></tr>
        """)

    return f"""
        <table class="striped">
        <thead>
        <tr><th>Book</th><th>Authors</th><th>Location</th></tr>
        </thead>
        <tbody>
        {"".join(rows)}
        </tbody></table>
        {pagination(
            base_url,
            page_no,
            more_results=more_results,
        ) if base_url else ''}
    """


@app.get("/places/<place_id>")
@page
async def view_place(request, place_id: int):
    page_no = int(request.args.get("page", 1))
    place = O.Place(place_id)
    books = O.Book.all(
        place_id=place.id,
        page_no=page_no - 1,
        page_size=PAGE_SIZE + 1,  # so we know if there would be more results
    )
    if request.ctx.authenticated:
        isbn_input_url = f"/places/{place_id}/add-book"
    else:
        isbn_input_url = ""

    return f"""
        {place:heading}
        {build_table(
            books,
            isbn_input_url=isbn_input_url,
            base_url=f"/places/{place_id}",
        )}
    """


@app.get("/places/<place_id>/viz")
@page
async def view_place_viz(request, place_id: int):
    page_no = int(request.args.get("page", 1))
    place = O.Place(place_id)
    books = O.Book.all(
        place_id=place.id,
        page_no=page_no - 1,
        page_size=PAGE_SIZE + 1,  # so we know if there would be more results
    )
    return f"""{place:heading} <div class="bookshelf">""" + "".join(
        f"{book:spine}" for book in books
    )


@app.post("/books/<book_id>/rename")
@authenticated
@fragment
async def rename_book(request, book_id: int):
    book = O.Book(book_id)
    title = D(request.form)["title"]
    if title:
        book.rename(title)
    return f"{book:heading}"


@app.post("/books/<book_id>/lend")
@authenticated
@fragment
async def lend_book(request, book_id: int):
    book = O.Book(book_id)
    lender = request.headers["HX-Prompt"].encode("ascii", "surrogateescape").decode("latin-1")
    if lender:
        book.lend_to(lender)
    return f"""<meta
        http-equiv="refresh"
        content="0; url=/books/{book_id}"
    >"""


@app.post("/books/<book_id>/return")
@authenticated
@fragment
async def return_book(request, book_id: int):
    book = O.Book(book_id)
    book.return_()
    return f"""<meta
        http-equiv="refresh"
        content="0; url=/books/{book_id}"
    >"""


@app.post("/books/<book_id>/fetch")
@authenticated
@fragment
async def fetch_book(request, book_id: int):
    book = O.Book(book_id)
    book.import_metadata()
    return f"""<meta
        http-equiv="refresh"
        content="0; url=/books/{book_id}"
    >"""


@app.delete("/books/<book_id>")
@authenticated
@fragment
async def delete_book(request, book_id: int):
    book = O.Book(book_id)
    place_id = book.place.id
    book.delete()
    return f"""<meta
        http-equiv="refresh"
        content="0; url=/places/{place_id}"
    >"""


@app.post("/places/<place_id>/rename")
@authenticated
@fragment
async def rename_place(request, place_id: int):
    place = O.Place(place_id)
    name = D(request.form)["name"]
    if name:
        place.rename(name)
    return f"{place:heading}"


@app.post("/places/<place_id>/add-book")
@authenticated
@fragment
async def add_book_by_isbn(request, place_id: int):
    place = O.Place(place_id)
    isbn = D(request.form)["isbn"]
    try:
        book = O.Book.new_from_isbn(isbn, place_id=place_id)
    except isbnlib.NotValidISBNError:
        return f"""
            <tr><td><input
                type="text"
                name="isbn"
                hx-post="/places/{place_id}/add-book"
                hx-swap="outerHTML"
                hx-target="closest tr"
                placeholder="insert ISBN"
                autofocus
            ></td></tr>
            <div hx-swap-oob="beforeend:#notifications">
                <span class="notification error">Invalid ISBN, try scanning again</span>
            </div>
        """
    if book.title:
        return f"""
            {book:table-row:title}
            <tr><td><input
                type="text"
                name="isbn"
                hx-post="/places/{place_id}/add-book"
                hx-swap="outerHTML"
                hx-target="closest tr"
                placeholder="insert ISBN"
                autofocus
            ></td></tr>
            <div hx-swap-oob="beforeend:#notifications">
                <span class="notification">Added <em>{book.title}</em></span>
            </div>
        """
    return f"""
        <form hx-put="/books/{book.id}">
            <input type="hidden" name="place_id" value="{place_id}">
            <label>Title <input name="title" placeholder="Title" required></label>
            <label>Author <input name="author" placeholder="Author"></label>
            <button type="submit">»</button>
        </form>
    """


@app.put("/books/<book_id>")
@authenticated
@fragment
async def put_book_data(request, book_id: int):
    data = D(request.form)
    book = O.Book(book_id)
    book.title = data["title"]
    book.author = data["author"]
    place_id = data["place_id"]
    book.save()
    return f"""
        <tr><td><input
            type="text"
            name="isbn"
            hx-post="/places/{place_id}/add-book"
            hx-swap="outerHTML"
            hx-target="closest tr"
            placeholder="insert ISBN"
            autofocus
        ></td></tr>
        <div hx-swap-oob="beforeend:#notifications">
            Added <em>{book.title}</em>
        </div>
    """


@app.get("/books/<book_id>")
@page
async def view_book(request, book_id: int):
    book = O.Book(book_id)
    return f"""
        <article>
            <header>
                <h3>{book:heading} {
                    f"{book:button-group}"
                    if request.ctx.authenticated
                    else ""
                }</h3>
            </header>
            {book:details}
        </article>
    """


@app.get("/books")
@page
async def list_books(request):
    page_no = int(request.args.get("page", 1))
    return build_table(
        O.Book.all(page_no=page_no-1, page_size=PAGE_SIZE + 1),
        base_url="/books",
        page_no=page_no,
    )


@app.get("/books/search")
@page
async def search_books(request):
    page_no = int(request.args.get("page", 1))
    query = D(request.args).get("q", "")
    books = O.Book.search(
        q=query,
        page_no=page_no - 1,
        page_size=PAGE_SIZE + 1,  # so we know if there would be more results
    )
    return build_table(
        books,
        base_url=f"/books/search?q={query}",
        page_no=page_no,
    )


@app.get("/htmx.js")
async def htmx_js(request):
    return await file("htmx.js", mime_type="text/javascript")


@app.get("/style.css")
async def style_css(request):
    return await file("style.css", mime_type="text/css")


@app.get("/pico.min.css")
async def pico_css(request):
    return await file("pico.min.css", mime_type="text/css")


@app.get("/logo.svg")
async def logo_svg(request):
    return await file("logo.svg", mime_type="image/svg+xml")
