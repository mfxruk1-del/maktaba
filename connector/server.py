"""Maktaba — personal Arabic library over MCP (streamable HTTP, secret-path access).

Env: MAKTABA_DIR (folder with library.db and books' img dirs), MAKTABA_TOKEN (secret path segment),
     MAKTABA_HOST / MAKTABA_PORT (bind address), MAKTABA_PUBLIC_HOST (e.g. maktaba.example.org).
Endpoint: https://<public host>/<token>/mcp
"""
import io, os, pathlib, sqlite3
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings
from arabic import norm

ROOT = pathlib.Path(os.environ.get("MAKTABA_DIR", ".")).resolve()
TOKEN = os.environ["MAKTABA_TOKEN"]
PUBLIC = os.environ.get("MAKTABA_PUBLIC_HOST", "maktaba.example.org")
HOST = os.environ.get("MAKTABA_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAKTABA_PORT", "8790"))

INSTRUCTIONS = """Maktaba: the user's personal Arabic library, for books that are NOT in al-Maktaba al-Shamela.
Organised like Shamela by WORK, each with one or more EDITIONS (list_books). Search a work id to cover all its
editions, and compare editions when a report's wording, chain or the editor's notes matter; the 'primary' edition is
the one to cite by default. Editions are 'typed' (digital text matched to the print) or 'OCR' (machine-read from page
scans with Kraken + the OpenITI Arabic model; diacritics dropped, headings sometimes cut off; quality varies, see
each edition's source note). Rules:
- Search is normalised (diacritics, hamza/alif forms, ى/ي, ة/ه ignored). Use 3+ letters per word; try one distinctive word
  (a name) if a longer phrase finds nothing, because OCR can break a single word.
- Before quoting OCR text as evidence, check it against the scan with get_page_image and quote from the image.
- Cite as: work title, edition (editor/publisher/year), printed page; say that the text is OCR when relevant.
- Never attribute text to a book unless it came from a tool result.
Three extra tools search al-Maktaba al-Shamela itself (8,587 books, NOT this library): semantic_search (by meaning),
nearby_words (given Arabic words standing near each other: for one-line remarks, formulas and proof-texts) and semantic_books
(which books are covered). Query in Arabic and scope meaning-searches to books or an author; unscoped, they search classical
authors only (died by 1300 AH) and rarely land on the right page. Results are candidates only: open the page with the Shamela
tools and verify the wording before quoting, and never treat an empty result as proof of absence.
START a question with search_digest: ONE call runs nearby_words and semantic_search together (25 results each) in every scope
you name and returns one line per book, about ten times less to read. On ten test questions (19 Nov 2026) the two searches
together reached direct passages in every scope, which neither did alone. Then open the pages worth reading. Use nearby_words
and semantic_search directly only to dig deeper in one scope.
Two more tools keep a NOTEBOOK of verified findings: findings_search (look there first when a matter comes up again) and
findings_add (save a passage only after its wording was checked on the Shamela page in this conversation, and tell the user).
The server also holds its own copy of every Shamela book: shamela_read_page, shamela_check_quote and shamela_contents read a page,
check a quote and list headings without the owner's PC. semantic_search and nearby_words leave the editors' footnotes out unless
asked (footnotes="include"), and with library="maktaba" they search this Maktaba library by meaning or by nearby words.
A third library, KUTUB (2,751 works whose text was not found in Shamela (checked by title and by content, by machine)), is searched
with library="kutub" on search_digest, semantic_search, nearby_words and semantic_books. Open its
results with kutub_read_page and check wording with check_quote (also for library="maktaba"). Kutub records no school or sect for its
authors: it holds Imami, Zaydi and Ibadi works beside Sunni ones, and typed text beside machine-read text; say who the author is
before relying on a page (the owner's labels cover only the authors on his list)."""

# The owner's own research rules (profile.md beside this file; personal, not part of the public code). Added to the instructions when present.
try:
    _profile = (pathlib.Path(__file__).resolve().parent / "profile.md").read_text(encoding="utf-8").strip()
    if _profile: INSTRUCTIONS += "\n\n" + _profile
except OSError:
    pass

mcp = FastMCP(
    "maktaba",
    instructions=INSTRUCTIONS,
    host=HOST,
    port=PORT,
    streamable_http_path=f"/{TOKEN}/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[PUBLIC, f"{HOST}:{PORT}", f"localhost:{PORT}", f"127.0.0.1:{PORT}"],
        allowed_origins=[f"https://{PUBLIC}", "https://claude.ai"],
    ),
)


def db():
    con = sqlite3.connect(f"file:{ROOT / 'library.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _book(con, book):
    """One edition, by edition id (or a work id that has a single edition)."""
    row = con.execute("SELECT * FROM books WHERE id=?", (book,)).fetchone()
    if row:
        return row
    eds = con.execute("SELECT * FROM books WHERE work=? ORDER BY primary_ed DESC, id", (book,)).fetchall()
    if len(eds) == 1:
        return eds[0]
    if eds:
        raise ValueError(f"'{book}' is a work with several editions; pass one edition id: "
                         + ", ".join(r["id"] for r in eds) + f" (primary: {eds[0]['id']})")
    ids = ", ".join(r["id"] for r in con.execute("SELECT id FROM books"))
    raise ValueError(f"Unknown book '{book}'. Available editions: {ids}")


def _edition_ids(con, book):
    """An edition id, or a work id (all its editions)."""
    eds = [r["id"] for r in con.execute("SELECT id FROM books WHERE work=?", (book,))]
    return eds or [_book(con, book)["id"]]


def _snippets(text, terms, max_lines=3):
    """Original lines whose normalised form contains a query term (with one line of context)."""
    lines = text.splitlines()
    normed = [norm(l) for l in lines]
    hits = [i for i, n in enumerate(normed) if any(t in n for t in terms)]
    out, used = [], set()
    for i in hits[:max_lines]:
        for j in range(max(0, i - 1), min(len(lines), i + 2)):
            if j not in used:
                used.add(j)
                out.append(lines[j])
        out.append("…")
    if not out:  # phrase broken across lines
        out = lines[:3] + ["…"]
    return "\n".join(out)


@mcp.tool()
def list_books() -> list[dict]:
    """List the library by work (like Shamela): each work with its editions (id, edition, source, kind,
    pages, has_scans, primary). Use a work id in search() to search every edition of that work, or an
    edition id for one edition; get_page/get_page_image take an edition id."""
    with db() as con:
        works = {}
        for r in con.execute("SELECT * FROM books ORDER BY work_title, primary_ed DESC, id"):
            w = works.setdefault(r["work"], {"work": r["work"], "title": r["work_title"], "author": r["author"],
                                             "editions": []})
            w["editions"].append({"id": r["id"], "edition": r["edition"], "source": r["source"],
                                  "kind": r["kind"], "pages": r["pages"], "has_scans": bool(r["img"]),
                                  "primary": bool(r["primary_ed"])})
        return list(works.values())


_PREFIXES = ("", "و", "ف", "ب", "ك", "ل", "وب", "ول", "وك", "فب", "فل", "فك")


def _variants(t):
    """A normalised word with the attached particles Arabic writes onto it (و ف ب ك ل, and لل for ال)."""
    v = {p + t for p in _PREFIXES}
    if t.startswith("ال") and len(t) > 3:
        v |= {p + "لل" + t[2:] for p in ("", "و", "ف")}
    return v


def _near(tokens, sets, distance):
    """True if one occurrence of every term (any variant) lies within `distance` words of the others."""
    pos = [[i for i, w in enumerate(tokens) if w in vs] for vs in sets]
    if any(not p for p in pos):
        return False
    first = pos[0]
    for i in first:
        if all(any(abs(j - i) <= distance for j in p) for p in pos[1:]):
            return True
    return False


@mcp.tool()
def search(query: str, book: str | None = None, mode: str = "phrase", limit: int = 20, distance: int = 5) -> dict:
    """Search the library's Arabic text.

    query: Arabic words (diacritics optional).
    mode="phrase" (default): the exact sequence, also inside longer words (حنيفة matches أبي حنيفة).
    mode="all": pages containing every word anywhere, also inside longer words.
    mode="word": every word as a WHOLE word (علم does not match تعلم or معلوم), still allowing the particles
      Arabic attaches in front (و ف ب ك ل، لل for ال: العلم matches والعلم، بالعلم، للعلم). Good for short words.
    mode="near": like "word", but the words must lie within `distance` words of each other, in any order
      (e.g. بيع near قبض) — for terms that sit close together without being adjacent.
    book: optional work id (searches all its editions) or edition id. limit: max hits (1-100).
    Returns hits with work, edition (book), page, printed page and matching lines.
    When comparing editions of a report, search the work id and compare the hits per edition.
    """
    q = norm(query)
    terms = [t for t in q.split() if t]
    if not terms:
        return {"query": query, "hits": [], "note": "empty query after normalisation"}
    limit = max(1, min(limit, 100))
    distance = max(1, min(distance, 50))
    with db() as con:
        params, where = [], ""
        if book:
            eds = _edition_ids(con, book)
            where = f" AND p.book IN ({','.join('?' * len(eds))})"
            params.extend(eds)
        if mode in ("word", "near"):
            sets = [_variants(t) for t in terms]
            fts = " AND ".join("(" + " OR ".join(f'"{v}"' for v in sorted(vs)) + ")" for vs in sets)
            cap = limit if mode == "word" else 5000
            sql = ("SELECT p.book, p.page, p.printed, p.text, p.norm FROM pages_words f JOIN pages p ON p.rowid = f.rowid "
                   "WHERE pages_words MATCH ?" + where + " ORDER BY p.book, p.page LIMIT ?")
            rows = con.execute(sql, [fts] + params + [cap]).fetchall()
            if mode == "near" and len(terms) > 1:
                rows = [r for r in rows if _near(r["norm"].split(), sets, distance)][:limit]
            match_terms = terms
        else:
            short = [t for t in terms if len(t) < 3]
            if short:  # trigram index needs 3+ characters; fall back to a scan
                likes = [q] if mode == "phrase" else terms
                sql = ("SELECT p.book, p.page, p.printed, p.text FROM pages p WHERE "
                       + " AND ".join("p.norm LIKE ?" for _ in likes) + where + " ORDER BY p.book, p.page LIMIT ?")
                rows = con.execute(sql, [f"%{t}%" for t in likes] + params + [limit]).fetchall()
            else:
                fts = f'"{q}"' if mode == "phrase" else " AND ".join(f'"{t}"' for t in terms)
                sql = ("SELECT p.book, p.page, p.printed, p.text FROM pages_fts f JOIN pages p ON p.rowid = f.rowid "
                       "WHERE pages_fts MATCH ?" + where + " ORDER BY p.book, p.page LIMIT ?")
                rows = con.execute(sql, [fts] + params + [limit]).fetchall()
            match_terms = [q] if mode == "phrase" else terms
        work = {r["id"]: r["work"] for r in con.execute("SELECT id, work FROM books")}
        hits = [{"work": work.get(r["book"]), "book": r["book"], "page": r["page"], "printed_page": r["printed"],
                 "lines": _snippets(r["text"], match_terms)} for r in rows]
    note = None if hits else ("No match. OCR may have split or misread a word: retry with one distinctive "
                              "word, a shorter form, or mode='all'.")
    return {"query": query, "mode": mode, "count": len(hits), "hits": hits, "note": note}


@mcp.tool()
def get_page(book: str, page: int = 0, context: int = 0, printed: str | None = None) -> dict:
    """Full text of one page of an edition (and optionally `context` pages before/after, max 3).
    Give `page` (the page number from search results) or `printed` (the printed page, e.g. "75" or "2/75").
    Text from OCR'd editions is machine-read: verify quotes with get_page_image."""
    context = max(0, min(context, 3))
    with db() as con:
        b = _book(con, book)
        if printed:
            r = con.execute("SELECT page FROM pages WHERE book=? AND printed=? ORDER BY page LIMIT 1",
                            (b["id"], str(printed))).fetchone()
            if not r:
                raise ValueError(f"{b['id']} has no printed page '{printed}'")
            page = r["page"]
        rows = con.execute("SELECT page, printed, text FROM pages WHERE book=? AND page BETWEEN ? AND ? "
                           "ORDER BY page", (b["id"], page - context, page + context)).fetchall()
        pages = [{"page": r["page"], "printed_page": r["printed"], "text": r["text"],
                  "links": _links(con, b["id"], r["page"])} for r in rows]
    if not rows:
        raise ValueError(f"{b['id']} has pages 1-{b['pages']}")
    return {"book": b["id"], "work": b["work"], "title": b["work_title"], "edition": b["edition"], "source": b["source"],
            "pages": pages}


_KIND = {"comments_on": "comments on", "commented_by": "commented on by", "same_passage": "same passage in",
         "from_fatawa": "same discussion in al-Fatawa al-Ridawiyya", "in_jadd": "same discussion in Jadd al-Mumtar"}


def _links(con, book_id, page):
    """Cross-references from links.db for one page (empty if links.db is missing)."""
    path = ROOT / "links.db"
    if not path.exists():
        return []
    lc = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = lc.execute("SELECT tgt_book, tgt_page, kind, label FROM links WHERE src_book=? AND src_page=? "
                      "ORDER BY kind, tgt_book, tgt_page", (book_id, page)).fetchall()
    lc.close()
    out = []
    for tb, tp, kind, label in rows:
        r = con.execute("SELECT printed FROM pages WHERE book=? AND page=?", (tb, tp)).fetchone()
        t = con.execute("SELECT edition FROM books WHERE id=?", (tb,)).fetchone()
        item = {"relation": _KIND.get(kind, kind), "book": tb, "page": tp,
                "printed_page": r["printed"] if r else None, "note": label}
        if tb == "radd-muhtar-halabi":
            item["shamela"] = {"book_id": 21613, "page_id": tp}
        out.append(item)
    return out


@mcp.tool()
def get_links(book: str, page: int) -> dict:
    """Cross-references for one page: which Radd al-Muhtar page a Jadd al-Mumtar gloss comments on (and back),
    where the same gloss or discussion appears in al-Fatawa al-Ridawiyya (and back), and the page with the same
    passage in another edition of the same work. Links are found automatically
    (by matching words), so open the target page and check it before relying on a link."""
    with db() as con:
        b = _book(con, book)
        return {"book": b["id"], "page": page, "links": _links(con, b["id"], page)}


@mcp.tool()
def get_page_image(book: str, page: int) -> Image:
    """The scanned image of one page of an edition that has scans (same page number as get_page/search)."""
    from PIL import Image as PILImage
    with db() as con:
        b = _book(con, book)
    if not b["img"]:
        raise ValueError(f"{b['id']} has no scans")
    path = ROOT / b["img"] / f"p{page:04d}.png"
    if not path.exists():
        raise ValueError(f"No scan for page {page}")
    im = PILImage.open(path).convert("L")
    if im.width > 1400:
        im = im.resize((1400, round(im.height * 1400 / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72, optimize=True)
    return Image(data=buf.getvalue(), format="jpeg")


@mcp.custom_route("/", methods=["GET"])
async def status(request):
    """Public status page (metadata only): OCR progress, works, editions and quality."""
    from starlette.responses import HTMLResponse
    import status_page
    return HTMLResponse(status_page.render())


import sem_tools  # meaning-search over Shamela, served by the local shamela-sem service
sem_tools.register(mcp)


if os.environ.get("MAKTABA_OCR_TOKEN"):
    import ocr_api
    ocr_api.register(mcp, os.environ["MAKTABA_OCR_TOKEN"])


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
