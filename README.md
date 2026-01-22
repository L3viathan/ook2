![Ook logo](/logo.svg)

_Manage your personal library of books_

**[Our instance](https://ook.vizuina.net)**

-----

With Ook, you can:

- Quickly enter a medium quantity of books (ideally with the help of a barcode scanner)
- Organize books in collections (e.g bookshelves, topics, ...)
- Mark books as lent out to someone
- Search for books in your library

### Self-Hosting

This was built for our (@sarnthil & @L3viathan) needs, but here's the code in case someone else wants to host a copy, too.

You'll need:

- Python 3.9 or higher
- The Python libraries listed in `requirements.txt`:
    - `sanic` (webserver)
    - `isbnlib` (for fetching book metadata)

Generate some random credentials, and run `sanic api` inside the Git checkout
with the environment variable `OOK_CREDS` set to some password, e.g.
`OOK_CREDS=foobar sanic api`.

I personally deploy this [via Ansible as a systemd unit, and put it behind
Caddy](https://github.com/L3viathan/ansibly/blob/master/roles/mainserver/tasks/ook.yml),
but you can obviously do this as you please.

The data lives in a SQLite database called `ook2.db`, in case you want to back this up.
