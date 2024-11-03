import os
import base64
import functools
from datetime import datetime
from types import CoroutineType

import isbnlib
from sanic import Sanic, HTTPResponse, html, file, redirect

import objects as O


PAGE_SIZE = 100
app = Sanic("ook2")
CORRECT_AUTH = os.environ["OOK_CREDS"]

def D(multival_dict):
    return {key: val[0] for key, val in multival_dict.items()}


@app.on_request
async def read_cookies(request):
    cookie = request.cookies.get("ook_auth")
    if cookie == CORRECT_AUTH:
        request.ctx.authenticated = True
    else:
        request.ctx.authenticated = False
    if request.cookies.get("prefers_shelf"):
        request.ctx.prefers_shelf = True
    else:
        request.ctx.prefers_shelf = False


def authenticated(route):
    @functools.wraps(route)
    async def wrapper(request, *args, **kwargs):
        if not request.ctx.authenticated:
            return HTTPResponse(
                body="401 Unauthorized",
                status=401,
            )
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
    lent_out = list(O.Book.all_lent_out())
    return f"""<article>
    <h4>Hello!</h4>
    <p>Here you can find most of the physical books we have at home. They are
    sorted into collections, or you can just look at all of them at once. If
    you want to borrow some (and you know one of us), that can probably be
    arranged.</p>
    {
        f"<p>Speaking of which, there are currently {len(lent_out)} books lent out:</p> {build_table(lent_out)}"
        if len(lent_out) > 1 else
        f"<p>Speaking of which, there is currently one book lent out:</p> {build_table(lent_out)}"
        if lent_out else ""
    }
    </article>"""
    return build_table(lent_out)


@app.get("/collections")
@page
async def list_collections(request):
    return "<br>".join(
        str(collection) for collection in O.Collection.all(order_by="name COLLATE NOCASE ASC")
    ) + ("""<button
        hx-get="/collections/new"
        hx-swap="outerHTML"
        class="button-new"
    >New collection</button>""" if request.ctx.authenticated else "")


@app.get("/collections/new")
@fragment
async def new_collection_form(request):
    return """
        <form
            hx-post="/collections/new"
            hx-swap="outerHTML"
            hx-encoding="multipart/form-data"
        >
            <input name="name" placeholder="name"></input>
            <button type="submit">»</button>
        </form>
    """


@app.post("/collections/new")
@authenticated
@fragment
async def new_collection(request):
    form = D(request.form)
    name = form["name"]
    collection = O.Collection.new(name)
    return f"""
        <button
            hx-get="/collections/new"
            hx-swap="outerHTML"
            class="button-new"
        >New collection</button>
        {collection}
        <br>
    """


def build_shelf(
    books,
    *,
    isbn_input_url=None,
    base_url=None,
    page_size=PAGE_SIZE,
    page_no=1,
):
    parts = ["""<div class="bookshelf">"""]
    if isbn_input_url:
        parts.append(build_isbn_input(isbn_input_url, mode="shelf"))
    more_results = False
    last_letter = None
    for i, book in enumerate(books):
        did_index = False
        if i == page_size:
            more_results = True
        else:
            letter = book.index_letter
            if letter != last_letter and i:
                parts.append(f"""<span class="nobreak"><div class="index"><span>{letter}</span></div>""")
                did_index = True
            last_letter = letter
            parts.append(f"{book:spine}")
            if did_index:
                parts.append("</span>")
    parts.append("</div>")
    if base_url:
        parts.append(pagination(
            base_url,
            page_no,
            more_results=more_results,
        ))
    return "".join(parts)


def build_isbn_input(isbn_input_url, mode="table"):
    if mode == "shelf":
        return f"""<input
            type="text"
            name="isbn"
            hx-post="{isbn_input_url}"
            hx-swap="outerHTML"
            placeholder="insert ISBN"
            autofocus
        >"""
    else:
        return f"""
            <tr><td colspan=3><input
                type="text"
                name="isbn"
                hx-post="{isbn_input_url}"
                hx-swap="outerHTML"
                hx-target="closest tr"
                placeholder="insert ISBN"
                autofocus
            ></td></tr>
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
    if isbn_input_url:
        rows.append(build_isbn_input(isbn_input_url, mode="table"))
    for i, book in enumerate(books):
        if i == page_size:
            more_results = True
        else:
            rows.append(f"{book:table-row:title,authors,location}")

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


def view_toggle_for(url, *, state=False):
    return f"""<label class="view-toggle"><input
        type="checkbox"
        role="switch"
        hx-post="/view?prefer={"off" if state else "on"}&redirect_url={url}"
        {"checked" if state else ""}
    >📚</label>"""


@app.post("/view")
async def set_view_pref(request):
    redirect_url = request.args.get("redirect_url", "/")
    response = html(f"""<meta
        http-equiv="refresh"
        content="0; url={redirect_url}"
    >""")
    if request.args.get("prefer") == "on":
        response.add_cookie(
            "prefers_shelf",
            "on",
            secure=True,
            httponly=True,
            samesite="Strict",
            max_age=60*60*24*365,  # roughly one year
        )
    else:
        response.delete_cookie("prefers_shelf")
    return response


@app.get("/collections/<collection_id>")
@page
async def view_collection(request, collection_id: int):
    page_no = int(request.args.get("page", 1))
    collection = O.Collection(collection_id)
    books = O.Book.all(
        collection_id=collection.id,
        offset=PAGE_SIZE * (page_no - 1),
        limit=PAGE_SIZE + 1,  # so we know if there would be more results
        order_by="sort_key ASC",
    )
    if request.ctx.authenticated:
        isbn_input_url = f"/collections/{collection_id}/add-book"
    else:
        isbn_input_url = ""

    return f"""
        {collection:heading}
        {view_toggle_for(
            f"/collections/{collection_id}",
            state=request.ctx.prefers_shelf,
        )}
        {build_shelf(
            books,
            isbn_input_url=isbn_input_url,
            base_url=f"/collections/{collection_id}",
            page_no=page_no,
        ) if request.ctx.prefers_shelf else build_table(
            books,
            isbn_input_url=isbn_input_url,
            base_url=f"/collections/{collection_id}",
            page_no=page_no,
        )}
    """


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
    collection_id = book.collection.id
    book.delete()
    return f"""<meta
        http-equiv="refresh"
        content="0; url=/collections/{collection_id}"
    >"""


@app.post("/collections/<collection_id>/rename")
@authenticated
@fragment
async def rename_collection(request, collection_id: int):
    collection = O.Collection(collection_id)
    name = D(request.form)["name"]
    if name:
        collection.rename(name)
    return f"{collection:heading}"


@app.post("/collections/<collection_id>/add-book")
@authenticated
@fragment
async def add_book_by_isbn(request, collection_id: int):
    collection = O.Collection(collection_id)
    isbn = D(request.form)["isbn"]
    display = "shelf" if request.ctx.prefers_shelf else "table"
    try:
        book = O.Book.new_from_isbn(isbn, collection_id=collection_id)
    except isbnlib.NotValidISBNError:
        return f"""
            {build_isbn_input(f"/collections/{collection_id}/add-book", mode=display)}
            <div hx-swap-oob="beforeend:#notifications">
                <span class="notification error">Invalid ISBN, try scanning again</span>
            </div>
        """
    if book.title:
        book_repr = (
            f"{book:table-row:title,authors,location}"
            if display == "table"
            else f"{book:spine}"
        )
        return f"""
            {build_isbn_input(f"/collections/{collection_id}/add-book", mode=display)}
            {book_repr}
            <div hx-swap-oob="beforeend:#notifications">
                <span class="notification">Added <em>{book.title}</em></span>
            </div>
        """
    return f"""
        <form hx-put="/books/{book.id}">
            <input type="hidden" name="collection_id" value="{collection_id}">
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
    book.authors = data["author"]
    collection_id = data["collection_id"]
    book.save()
    display = "shelf" if request.ctx.prefers_shelf else "table"
    return f"""{build_isbn_input(f"/collections/{collection_id}/add-book", mode=display)}<div
        hx-swap-oob="beforeend:#notifications"
        >Added <em>{book.title}</em></div>"""


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
            {f"{book:details-editable}" if request.ctx.authenticated else f"{book:details}"}
        </article>
    """


@app.get("/books/<book_id>/authors-form")
@fragment
async def edit_authors_form(request, book_id: int):
    book = O.Book(book_id)
    return f"""<td><input
        hx-post="/books/{book_id}/authors"
        hx-swap="outerHTML"
        hx-trigger="blur"
        hx-target="closest td"
        name="authors"
        value="{book.authors}"
    ></td>"""


@app.post("/books/<book_id>/authors")
@authenticated
@fragment
async def change_authors(request, book_id: int):
    book = O.Book(book_id)
    form = D(request.form)
    if authors := form["authors"]:
        book.authors = authors
        book.sort_key = book.calculate_sort_key()
        book.save()
    return f"{book:authors-editable}"


@app.get("/books")
@page
async def list_books(request):
    page_no = int(request.args.get("page", 1))
    books = O.Book.all(
        offset=PAGE_SIZE * (page_no - 1),
        limit=PAGE_SIZE + 1,  # so we know if there would be more results
        order_by="sort_key ASC",
    )
    return f"""
        {view_toggle_for(
            f"/books",
            state=request.ctx.prefers_shelf,
        )}
        {build_shelf(
            books,
            base_url="/books",
            page_no=page_no,
        ) if request.ctx.prefers_shelf else build_table(
            books,
            base_url="/books",
            page_no=page_no,
        )}
    """


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
