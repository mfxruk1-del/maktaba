# -*- coding: utf-8 -*-
"""Pages of the Kutub library (~/kutub/index.sqlite3, opened read-only and immutable, never written): read a page, check a quote.
Also the same quote check for the owner's own Maktaba library (~/library/library.db): mk_check().
Paths: KUTUB_DB and MAKTABA_DB in the environment, else the two files named here under the home folder.

Kutub text is machine-read for the most part (OCR noise), the editors' notes are NOT split from the author's words and there is no
headings table. A page is named by its `idx` (the "page" of a search result); volume / page_no are the printed numbers when known.
The matching is pagestore.find: diacritics, punctuation and hamza / ya / ta-marbuta spelling are ignored, the words must stand in
the same order with nothing between them. Reply shapes follow pagestore where that makes sense."""
import os, sqlite3
import pagestore

DB = os.environ.get("KUTUB_DB", os.path.join(os.path.expanduser("~"), "kutub", "index.sqlite3"))
LIB_DB = os.environ.get("MAKTABA_DB", os.path.join(os.path.expanduser("~"), "library", "library.db"))
SOURCE = "Kutub: machine-read text for the most part (OCR noise possible); the editors' notes are not split from the author's words"
NOW_AH = 1448


def connect():
    if not os.path.exists(DB): raise RuntimeError("the Kutub store is not on this server")
    con = sqlite3.connect("file:%s?mode=ro&immutable=1" % DB, uri=True); con.row_factory = sqlite3.Row
    return con


def _book(con, slug):
    r = con.execute("SELECT slug, title, title_arabic, author, author_slug, year, pages_done, status FROM books WHERE slug=?", (str(slug),)).fetchone()
    if r is None: return None
    y = r["year"]
    return {"library": "kutub", "book": r["slug"], "title": (r["title_arabic"] or "").strip() or r["title"], "title_latin": r["title"], "author": r["author"],
            "author_slug": r["author_slug"], "died_ah": y if isinstance(y, int) and 0 < y <= NOW_AH else None, "pages": r["pages_done"], "status": r["status"]}


def book(slug):
    con = connect()
    try: return _book(con, slug)
    finally: con.close()


def _missing(slug):
    return {"error": "no book '%s' in the Kutub store: `book` is the slug a search result gives (semantic_books with library=\"kutub\" lists them)" % slug}


def _page(r, chars, around=None, radius=600):
    text = pagestore.render(r["text"]); out = {"page": r["idx"], "volume": r["volume"], "printed_page": r["page_no"]}
    if around:
        hit = pagestore.find(text, around)
        if hit and hit["exact"]:
            a = max(0, hit["start_char"] - radius); b = min(len(text), hit["end_char"] + radius)
            out["text"] = ("… " if a > 0 else "") + text[a:b] + (" …" if b < len(text) else ""); out["text_is_excerpt_around_the_phrase"] = True
        else:
            out["text"] = text[:chars]; out["phrase_not_found_on_this_page"] = True
    else: out["text"] = text[:chars]
    if not around and len(text) > chars: out["text_cut_at"] = chars; out["text_length"] = len(text)
    return out


def read(slug, idx=None, volume=None, page_no=None, context=0, chars=6000, around=None):
    con = connect()
    try:
        b = _book(con, slug)
        if b is None: return _missing(slug)
        if b["status"] != "done": return {"error": "this book has no text in the Kutub store (status: %s)" % b["status"], "book": b}
        note = None
        if idx is not None: rows = con.execute("SELECT * FROM pages WHERE slug=? AND idx=?", (b["book"], int(idx))).fetchall()
        elif page_no is not None and volume is not None:
            rows = con.execute("SELECT * FROM pages WHERE slug=? AND volume=? AND page_no=? ORDER BY idx", (b["book"], int(volume), int(page_no))).fetchall()
        elif page_no is not None: rows = con.execute("SELECT * FROM pages WHERE slug=? AND page_no=? ORDER BY idx", (b["book"], int(page_no))).fetchall()
        else:
            return {"error": "give page (the `page` of a search result), or printed_page (with volume when the book has volumes)", "book": b}
        if not rows: return {"error": "no such page in this book", "book": b, "hint": "give page (the `page` of a search result) or printed_page with volume"}
        r = rows[0]; i = r["idx"]; context = max(0, min(int(context or 0), 3)); chars = max(300, min(int(chars or 6000), 20000))
        lo = con.execute("SELECT * FROM pages WHERE slug=? AND idx<? ORDER BY idx DESC LIMIT ?", (b["book"], i, max(context, 1))).fetchall()[::-1]
        hi = con.execute("SELECT * FROM pages WHERE slug=? AND idx>? ORDER BY idx LIMIT ?", (b["book"], i, max(context, 1))).fetchall()
        pages = [_page(x, chars) for x in lo[-context:]] if context else []
        pages.append(dict(_page(r, chars, around), asked_for=True)); pages += [_page(x, chars) for x in hi[:context]] if context else []
        out = {"book": b, "pages": pages, "previous_page": lo[-1]["idx"] if lo else None, "next_page": hi[0]["idx"] if hi else None, "source": SOURCE}
        if len(rows) > 1: note = "%d pages carry this printed number: pages %s; the first is shown" % (len(rows), [x["idx"] for x in rows][:12])
        if note: out["note"] = note
        return out
    finally: con.close()


# ---- quote check shared by Kutub and Maktaba: pages are (number, text) in reading order --------------------------------------------
def _keys(text):
    return [k for k, _, _ in pagestore._words(text)]


def _check_page(pages, at, quote):
    """pages: [(number, text)] = the page asked for with the one before and after. The page itself first, then the three in a row."""
    best = None
    for single in [p for p in pages if p[0] == at] + [None]:
        if single is not None: text = single[1]; spans = [(0, single[0])]
        else:
            text = ""; spans = []
            for n, t in pages: spans.append((len(text), n)); text += t + "\n"
        h = pagestore.find(text, quote) if text else None
        if not h: continue
        page_of = lambda pos: [n for s, n in spans if s <= pos][-1]
        if h["exact"]:
            p0 = page_of(h["start_char"]); p1 = page_of(h["end_char"] - 1)
            return {"found": True, "page": p0, "runs_on_to_page": p1 if p1 != p0 else None, "on_the_page_asked_for": p0 == at,
                    "words_on_the_page": text[h["start_char"]:h["end_char"]], "words_checked": h["words"]}
        if h["run"] and (best is None or h["run"] > best["longest_run_of_words"]):
            best = {"longest_run_of_words": h["run"], "of": h["words"], "starting_at_quote_word": h["quote_word_from"], "page": page_of(h["start_char"]),
                    "words_on_the_page": text[h["start_char"]:h["end_char"]]}
    return {"found": False, "searched": "page %s and the page before and after" % at, "closest": best,
            "note": "not found as an unbroken run of words; the wording may differ, or stand on another page"}


def _check_book(pages, quote, limit=8):
    """pages: iterator of (number, text) over the whole book. Exact places first (also across a page break); when there is none, the
    longest run of the quote's words, looked for only on pages that hold two of its words side by side."""
    Q = _keys(quote); m = len(Q); needle = " " + " ".join(Q) + " "; pairs = [" %s %s " % (Q[i], Q[i + 1]) for i in range(m - 1)]
    hits = []; maybe = []; prev = None
    for n, text in pages:
        keys = _keys(text); line = " " + " ".join(keys) + " "
        if needle in line:
            h = pagestore.find(text, quote)
            if h and h["exact"]: hits.append({"page": n, "words_on_the_page": text[h["start_char"]:h["end_char"]]})
        elif prev is not None and m > 1 and needle in " " + " ".join(prev[2][-(m - 1):] + keys[:m - 1]) + " ":
            both = prev[1] + "\n" + text; h = pagestore.find(both, quote)
            if h and h["exact"]: hits.append({"page": prev[0], "runs_on_to_page": n, "words_on_the_page": both[h["start_char"]:h["end_char"]]})
        elif not hits and len(maybe) < 400 and any(p in line for p in pairs): maybe.append((n, text))
        if len(hits) >= limit: break
        prev = (n, text, keys)
    out = {"found": bool(hits), "searched": "the whole book", "places": hits}
    if not hits:
        best = None
        for n, text in maybe:
            h = pagestore.find(text, quote)
            if h and not h["exact"] and h["run"] and (best is None or h["run"] > best["longest_run_of_words"]):
                best = {"page": n, "longest_run_of_words": h["run"], "of": h["words"], "starting_at_quote_word": h["quote_word_from"], "words_on_the_page": text[h["start_char"]:h["end_char"]]}
        if best: out["closest"] = best
    return out


def check(slug, quote, idx=None):
    """Do these Arabic words stand in this Kutub book? idx given: that page and its neighbours; not given: the whole book."""
    con = connect()
    try:
        b = _book(con, slug)
        if b is None: return _missing(slug)
        if len(_keys(quote)) < 3: return {"error": "give at least three Arabic words to check"}
        if idx is None:
            it = ((r[0], pagestore.render(r[1])) for r in con.execute("SELECT idx, text FROM pages WHERE slug=? ORDER BY idx", (b["book"],)))
            out = _check_book(it, quote); extra = {r[0]: (r[1], r[2]) for p in out["places"] for r in con.execute("SELECT idx, volume, page_no FROM pages WHERE slug=? AND idx=?", (b["book"], p["page"]))}
            for p in out["places"]: p["volume"], p["printed_page"] = extra.get(p["page"], (None, None))
        else:
            r = con.execute("SELECT idx FROM pages WHERE slug=? AND idx=?", (b["book"], int(idx))).fetchone()
            if r is None: return {"error": "no such page in this book", "book": b}
            lo = con.execute("SELECT idx, volume, page_no, text FROM pages WHERE slug=? AND idx<? ORDER BY idx DESC LIMIT 1", (b["book"], int(idx))).fetchall()
            me = con.execute("SELECT idx, volume, page_no, text FROM pages WHERE slug=? AND idx>=? ORDER BY idx LIMIT 2", (b["book"], int(idx))).fetchall()
            rows = lo + me; out = _check_page([(x["idx"], pagestore.render(x["text"])) for x in rows], int(idx), quote)
            if out["found"]:
                x = next(x for x in rows if x["idx"] == out["page"]); out["volume"] = x["volume"]; out["printed_page"] = x["page_no"]
        return dict({"book": b}, **out, source=SOURCE)
    finally: con.close()


# ---- the owner's own library (library.db: books(id, work, ...), pages(book, page, printed, text, norm)) --------------------------------
def mk_check(book, quote, page=None):
    """The same check in the Maktaba library. book: an edition id (or a work id that has one edition). page: Maktaba's page number
    (the one get_page takes); given = that page and its neighbours, not given = the whole book."""
    if not os.path.exists(LIB_DB): return {"error": "the Maktaba library is not on this server"}
    con = sqlite3.connect("file:%s?mode=ro" % LIB_DB, uri=True); con.row_factory = sqlite3.Row
    xp = os.path.join(os.path.dirname(LIB_DB), "texts_extra.db")           # the page texts of the imported books
    if os.path.exists(xp): con.execute("ATTACH DATABASE ? AS x", ("file:%s?mode=ro" % xp,))
    con.execute("CREATE TEMP VIEW allpages AS SELECT book, page, printed, text FROM main.pages" + (" UNION ALL SELECT book, page, printed, text FROM x.pages" if os.path.exists(xp) else ""))
    try:
        b = con.execute("SELECT * FROM books WHERE id=?", (str(book),)).fetchone()
        if b is None:
            eds = con.execute("SELECT * FROM books WHERE work=? ORDER BY primary_ed DESC, id", (str(book),)).fetchall()
            if len(eds) == 1: b = eds[0]
            elif eds: return {"error": "'%s' is a work with several editions; give one edition id: %s" % (book, ", ".join(e["id"] for e in eds))}
            else: return {"error": "no book '%s' in the Maktaba library (list_books shows the edition ids)" % book}
        info = {"library": "maktaba", "book": b["id"], "title": b["title"], "author": b["author"], "edition": b["edition"], "text_kind": b["kind"], "pages": b["pages"]}
        if len(_keys(quote)) < 3: return {"error": "give at least three Arabic words to check"}
        src = "Maktaba: %s text%s" % (b["kind"] or "", "; OCR must be checked against the scan (get_page_image) before quoting" if (b["kind"] or "").upper() == "OCR" else "")
        if page is None:
            out = _check_book(((r["page"], r["text"] or "") for r in con.execute("SELECT page, text FROM allpages WHERE book=? ORDER BY page", (b["id"],))), quote)
            pr = {r["page"]: r["printed"] for p in out["places"] for r in con.execute("SELECT page, printed FROM allpages WHERE book=? AND page=?", (b["id"], p["page"]))}
            for p in out["places"]: p["printed_page"] = pr.get(p["page"])
        else:
            rows = con.execute("SELECT page, printed, text FROM allpages WHERE book=? AND page BETWEEN ? AND ? ORDER BY page", (b["id"], int(page) - 1, int(page) + 1)).fetchall()
            if not any(r["page"] == int(page) for r in rows): return {"error": "no such page in this book", "book": info}
            out = _check_page([(r["page"], r["text"] or "") for r in rows], int(page), quote)
            if out["found"]: out["printed_page"] = next(r["printed"] for r in rows if r["page"] == out["page"])
        return dict({"book": info}, **out, source=src)
    finally: con.close()
