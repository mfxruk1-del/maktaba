"""Shamela meaning-search service. Local only (127.0.0.1:8791); the Maktaba MCP server calls it.

Data: ~/semsearch/data (built on Modal by prep_serve.py). Search code: semcore.py (same code the build self-test used).
Run by systemd unit shamela-sem.service. Stop it any time with: sudo systemctl stop shamela-sem
"""
import os, re, sys, json, threading, time, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

import semcore

DATA = os.environ.get("SEM_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
HOST = os.environ.get("SEM_HOST", "127.0.0.1")
PORT = int(os.environ.get("SEM_PORT", "8791"))
STATE = {"s": None, "error": None, "loading_since": None}
LOAD = threading.Lock()
RUN = threading.Lock()


def searcher():
    with LOAD:
        if STATE["s"] is None:
            STATE["loading_since"] = time.time()
            try:
                STATE["s"] = semcore.Searcher(DATA); STATE["error"] = None
            except Exception as e:
                STATE["error"] = repr(e)[:300]; raise
    return STATE["s"]


MK_DIR = os.environ.get("SEM_DATA_MAKTABA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_maktaba"))


KT_DIR = os.environ.get("SEM_DATA_KUTUB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_kutub"))
LIBS = ("shamela", "maktaba", "kutub")


def fold(t):
    """A Latin name or a slug as plain lower-case letters (diacritics, ʿ ʾ and hyphens off): Kutub writes its authors in transliteration."""
    t = unicodedata.normalize("NFD", str(t or "").lower()); t = "".join(c for c in t if not unicodedata.combining(c))
    for ch in "ʿʾ'’‘`": t = t.replace(ch, "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def pick(p):
    """(searcher, library). library = "shamela" (default) | "maktaba" (the small separate index of the owner's own books, which are not
    in Shamela) | "kutub" (the Kutub works whose text was not found in Shamela; keyword-only as long as that index has no vectors)."""
    s = searcher(); lib = str(p.get("library") or "shamela").lower()
    if lib in ("shamela", ""): return s, "shamela"
    if lib == "kutub": lib = "maktaba"                     # since 20 Nov 2026 the imported books are part of the Maktaba library
    if lib not in LIBS: raise KeyError("library must be shamela or maktaba")
    key, folder, name = ("mk", MK_DIR, "Maktaba") if lib == "maktaba" else ("kt", KT_DIR, "Kutub")
    with LOAD:
        if STATE.get(key) is None:
            if not os.path.isdir(folder): raise RuntimeError("the %s index is not on this server yet" % name)
            m = semcore.Searcher(folder, load_model=False); m.model = s.model; m.flag_editor = False
            m.by_sid = {b["shamela_id"]: b for b in m.books}
            m.folded = {b["shamela_id"]: fold(b.get("author_latin") or b.get("author")) + " | " + fold(b.get("author_slug")) for b in m.books}
            STATE[key] = m
    return STATE[key], lib


def preset_for(lib, p):
    """Shamela: as asked ("auto" = classical authors only, unless books, an author or dates are named). Maktaba and Kutub are searched
    whole unless "classical" is asked for by name: there "auto" means "all" (the connector always sends "auto", which until now cut an
    unscoped Maktaba search down to the authors who died by 1300 AH)."""
    v = p.get("preset") or "auto"
    return v if lib == "shamela" else ("all" if v == "auto" else v)


def lib_category(lib, p):
    """The category filter. Shamela: as given. Kutub has no categories; Maktaba knows only its two kinds of text. Anything else is refused
    with a clear message instead of being ignored or quietly matching nothing."""
    c = p.get("category") or None
    if lib == "shamela" or c is None: return c
    if lib == "maktaba": return {"typed": "typed", "ocr": "OCR", "imported": "imported"}.get(str(c).strip().lower(), c)      # a kind of text, or a shelf name (both stand in cat_name)
    kind = None
    if kind: return kind
    raise KeyError('category: library "kutub" has no categories (narrow it with author, books, died_after / died_before)' if lib == "kutub" else
                   'category: library "maktaba" knows only "typed" and "OCR", not Shamela\'s categories')


def lib_scope(s, lib, p):
    """The book and author filters of a request as the Searcher takes them: {"shamela_ids", "author"} or {"error"}. Shamela: as given.
    Maktaba / Kutub: `books` (Maktaba edition or work ids, Kutub slugs) become index ids. A Kutub author may be given in Latin letters,
    as an author slug, or in Arabic (known only where the same author also has a book in Shamela: books.json "author_ar")."""
    ids = p.get("shamela_ids") or None; author = p.get("author") or None
    if lib == "shamela": return {"shamela_ids": ids, "author": author}
    ids = [int(x) for x in ids] if ids else []
    for name in [str(x).strip() for x in (p.get("books") or []) if str(x).strip()]:
        hit = [b["shamela_id"] for b in s.books if name in ((b.get("maktaba_id"), b.get("work")) if lib == "maktaba" else (b.get("kutub_slug"),))]
        if not hit: raise KeyError("no book '%s' in the %s index (semantic_books with library=\"%s\" lists them)" % (name, lib, lib))
        ids += hit
    if lib in ("kutub", "maktaba") and author:
        a = semcore.norm(author).strip() if re.search("[ء-ي]", author) else ""; f = fold(author)
        hit = {b["shamela_id"] for b in s.books if (a and a in semcore.norm((b.get("author_ar") or "") + " " + (b.get("author") or ""))) or (f and f in s.folded[b["shamela_id"]])}
        if not hit:
            return {"error": "no Kutub author matches '%s'. Kutub names its authors in Latin letters (try part of the name or of the author slug, e.g. \"ibn "
                             "taymiyya\"); the Arabic name is known only for authors who also have a book in Shamela. semantic_books(library=\"kutub\", title=...) "
                             "shows a book's author." % author}
        ids = [i for i in ids if i in hit] if ids else sorted(hit); author = None
        if not ids: return {"error": "no Kutub book matches both the books and the author given"}
    return {"shamela_ids": ids or None, "author": author}


def mk_rows(s, r):
    """Maktaba results: say which Maktaba book and page to open (Maktaba's get_page), not Shamela ids."""
    ids = {b["shamela_id"]: b for b in s.books}
    def fix(x):
        b = ids.get(x.get("shamela_id"))
        if b is None: return x
        y = {"library": "maktaba", "book": b["maktaba_id"], "page": x.get("shamela_page_id"), "printed_page": x.get("page") if (x.get("page") or -1) >= 0 else None,
             "title": b["title"], "author": b["author"], "died_ah": b["death"], "edition": b.get("edition"), "text_kind": b.get("kind") or b["cat_name"].replace("Maktaba ", "")}
        if (x.get("part") or -1) > 0: y["volume"] = x["part"]
        for k_ in ("shelf", "edition_of", "author_latin"):
            if b.get(k_): y[k_] = b[k_]
        if b.get("flag"): y["book_note"] = b["flag"]
        for k, v in x.items():
            if k not in ("shamela_id", "shamela_page_id", "part", "page", "title", "author", "died_ah", "category"): y[k] = v
        if "same_words_in" in y: y["same_words_in"] = [fix(z) for z in y["same_words_in"]]
        return y
    r["results"] = [fix(x) for x in r.get("results", [])]
    if "by_book" in r:
        r["by_book"] = [dict({k: v for k, v in x.items() if k != "shamela_id"}, book=ids[x["shamela_id"]]["maktaba_id"]) if x.get("shamela_id") in ids else x for x in r["by_book"]]
    r["library"] = ("maktaba: open a result with Maktaba's get_page(book, page); OCR editions must be checked against the scan before quoting; text_kind \"imported\" = an "
                    "imported book (mostly machine-read, no scan, editors' notes not split): check its wording with check_quote; edition_of names the Shamela work it is another edition of")
    return r


KT_NOTE = ("kutub: books by Sunni authors: works that Shamela lacks, and other editions of works it has (sorted on 20 Nov 2026 by machine and by name lists, not checked book by book). "
           "Open a result with kutub_read_page(book, page) and check wording with check_quote(library=\"kutub\"). \"shelf\" is the subject shelf (Shamela's category "
           "names, found by machine, about 7 in 10 right); \"edition_of\" names the Shamela work this book is another edition of. Typed text stands beside "
           "machine-read text (editors' notes not split off, no chapter path). Say who the author is before relying on a page; the owner's labels cover only "
           "the authors on his list")


def kt_rows(s, r):
    """Kutub results: say which Kutub book (slug) and page (idx) to open with kutub_read_page, not Shamela ids."""
    ids = s.by_sid; num = lambda v: v if v is not None and v >= 0 else None
    def fix(x):
        b = ids.get(x.get("shamela_id"))
        if b is None: return x
        y = {"library": "kutub", "book": b["kutub_slug"], "page": x.get("shamela_page_id"), "volume": num(x.get("part")), "printed_page": num(x.get("page")),
             "title": b["title"], "author": b.get("author"), "died_ah": b.get("death")}
        if b.get("author_ar"): y["author_ar"] = b["author_ar"]
        if b.get("maybe_shamela_id"): y["maybe_also_in_shamela"] = b["maybe_shamela_id"]
        if b.get("cat_name") and b["cat_name"] != "Kutub": y["shelf"] = b["cat_name"]
        if b.get("edition_of"): y["edition_of"] = b["edition_of"]
        if b.get("flag"): y["book_note"] = b["flag"]
        for k, v in x.items():
            if k not in ("shamela_id", "shamela_page_id", "part", "page", "title", "author", "died_ah", "category", "from"): y[k] = v
        if "same_words_in" in y: y["same_words_in"] = [fix(z) for z in y["same_words_in"]]
        return y
    r["results"] = [fix(x) for x in r.get("results", [])]
    if "by_book" in r:
        r["by_book"] = [dict({k: v for k, v in x.items() if k != "shamela_id"}, book=ids[x["shamela_id"]]["kutub_slug"]) if x.get("shamela_id") in ids else x for x in r["by_book"]]
    r["library"] = KT_NOTE
    return r


def finish(lib, s, r):
    """Labels for every library, then the library's own shape: chapter paths for Shamela, book / page names for Maktaba and Kutub."""
    if lib == "shamela": return add_chapters(add_labels(r, s))
    return (mk_rows if lib == "maktaba" else kt_rows)(s, add_labels(r, s, lib))


LABELS = {}                                              # library -> {"mtime", "by_id", "short"}
LABEL_FILE = os.environ.get("SEM_LABELS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels.json"))


def label_maps(s, lib="shamela"):
    """labels.json as {index id -> note} and {index id -> short tag} for one library; read again whenever the file changes. A book is
    labelled when its author's name equals a name in "authors" (in Maktaba also without the "(ت ...)" tail, in Kutub the Arabic name
    where known), and in Kutub also when its author_slug stands in the label's optional "kutub_slugs"."""
    m = os.path.getmtime(LABEL_FILE); L = LABELS.get(lib)
    if L is None or L["mtime"] != m:
        by = {}; short = {}
        for lab in json.load(open(LABEL_FILE, encoding="utf-8")).get("labels", []):
            names = set(semcore.norm(a).strip() for a in lab.get("authors", [])); slugs = set(lab.get("kutub_slugs") or []) if lib in ("kutub", "maktaba") else set()
            for b in s.books:
                hit = semcore.norm(b.get("author") or "").strip() in names
                if not hit and lib == "maktaba": hit = semcore.norm(re.sub(r"\s*\(.*?\)\s*$", "", b.get("author") or "")).strip() in names
                if not hit and lib in ("kutub", "maktaba"): hit = b.get("author_slug") in slugs or (bool(b.get("author_ar")) and semcore.norm(b["author_ar"]).strip() in names)
                if hit: by[b["shamela_id"]] = lab["note"]; short[b["shamela_id"]] = str(lab.get("short") or lab.get("id") or "listed")
        LABELS[lib] = L = {"mtime": m, "by_id": by, "short": short}
    return L


def add_labels(r, s, lib="shamela"):
    """Authors the user wants SHOWN WITH A LABEL (labels.json: exact author names -> a note). Adds "author_note" to their results and
    hides nothing. The file is read again whenever it changes. Any error here leaves the result as it was."""
    try:
        by = label_maps(s, lib)["by_id"]
        if by:
            for x in r.get("results", []):
                if x.get("shamela_id") in by: x["author_note"] = by[x["shamela_id"]]
                for z in x.get("same_words_in") or []:
                    if z.get("shamela_id") in by: z["author_note"] = by[z["shamela_id"]]
    except Exception: pass
    return r


def add_chapters(r):
    """Say where each Shamela result sits in its book ("كتاب ... > باب ... > فصل ..."), read from the book's own table of contents in the
    page store (chapters.py). Only adds a field; a book with no table of contents, or any error here, leaves the result as it was."""
    try:
        import pagestore, chapters
        con = pagestore.connect()
        try:
            def put(x):
                if x.get("shamela_id") is None or x.get("shamela_page_id") is None: return
                ch = chapters.chapter(con, x["shamela_id"], x["shamela_page_id"])
                if ch: x["chapter"] = ch
            for x in r.get("results", []):
                put(x)
                for z in x.get("same_words_in") or []: put(z)
        finally: con.close()
    except Exception: pass
    return r


def do_search(p):
    s, lib = pick(p); mk = lib != "shamela"; sc = lib_scope(s, lib, p)
    if sc.get("error"): return {"error": sc["error"], "results": []}
    kw = dict(shamela_ids=sc["shamela_ids"], author=sc["author"],
              category=lib_category(lib, p), died_after=p.get("died_after"), died_before=p.get("died_before"),
              footnotes=p.get("footnotes") or "include", mode=p.get("mode") or "hybrid", preset=preset_for(lib, p),
              per_book=p.get("per_book"), hide_editor_pages=bool(p.get("hide_editor_pages")))
    more = [q for q in (p.get("queries") or []) if q and str(q).strip()]
    with RUN:
        if more: r = s.search_multi([str(p.get("query") or "")] + more, limit=int(p.get("limit") or 8), chars=int(p.get("chars") or 350), **kw)
        else: r = s.search(str(p.get("query") or ""), limit=int(p.get("limit") or 8), chars=int(p.get("chars") or 350), **kw)
    r.pop("fused_ids", None); r.pop("uncapped_ids", None)
    return finish(lib, s, r)


def do_near(p):
    s, lib = pick(p); mk = lib != "shamela"; sc = lib_scope(s, lib, p)
    if sc.get("error"): return {"error": sc["error"], "results": []}
    num = lambda k, d: int(p.get(k)) if p.get(k) is not None else d
    with RUN:
        r = s.near(p.get("phrases") or [], window=num("window", 8), shamela_ids=sc["shamela_ids"],
                      author=sc["author"], category=lib_category(lib, p), died_after=p.get("died_after"),
                      died_before=p.get("died_before"), preset=preset_for(lib, p), footnotes=p.get("footnotes") or "include",
                      limit=num("limit", 30), chars=num("chars", 350), per_book=num("per_book", 2), sort=p.get("sort") or "best",
                      group=p.get("group") is not False, hide_editor_pages=bool(p.get("hide_editor_pages")))
    return finish(lib, s, r)


def do_digest(p):
    """One call for a whole question (digest.py): both searches in every scope, merged on the server into one line per book."""
    s, lib = pick(p)
    import digest, pagestore, chapters
    try: short = label_maps(s, lib)["short"]                # reads labels.json again when it changed
    except Exception: short = {}
    if lib != "shamela":                                    # no categories and no chapter paths there; a library without vectors runs on nearby-words alone
        return digest.run(s, p, RUN, label=lambda sid: short.get(sid), lib=lib, scope_fix=lambda sc: lib_scope(s, lib, sc), book_of=s.by_sid.get)
    try: con = pagestore.connect()
    except Exception: con = None

    def ch(sid, pid):
        try: return chapters.chapter(con, sid, pid, each=40) if con is not None else None
        except Exception: return None
    try: return digest.run(s, p, RUN, chapter=ch, label=lambda sid: short.get(sid))
    finally:
        if con is not None: con.close()


def do_books(p):
    s, lib = pick(p); mk = lib == "maktaba"; sc = lib_scope(s, lib, p)
    if sc.get("error"): return {"error": sc["error"], "matched": 0, "books": []}
    sel = s.scope(sc["shamela_ids"], sc["author"], lib_category(lib, p), p.get("died_after"), p.get("died_before"))
    if sel is None: sel = s.books
    title = semcore.norm(str(p.get("title") or "")).strip()
    if title: sel = [b for b in sel if title in semcore.norm(b.get("title") or "")]
    limit = max(1, min(int(p.get("limit") or 40), 200))
    rows = sorted(sel, key=lambda b: -b["passages"])
    if lib == "kutub":
        return {"matched": len(sel), "passages": int(sum(b["passages"] for b in sel)),
                "books": [dict({"book": b["kutub_slug"], "title": b.get("title"), "author": b.get("author"), "author_slug": b.get("author_slug"), "died_ah": b.get("death"),
                                "passages": b["passages"]}, **({"author_ar": b["author_ar"]} if b.get("author_ar") else {}), **({"shelf": b["cat_name"]} if b.get("cat_name") not in (None, "Kutub") else {}),
                               **({"edition_of": b["edition_of"].get("title")} if b.get("edition_of") else {}),
                               **({"maybe_also_in_shamela": b["maybe_shamela_id"]} if b.get("maybe_shamela_id") else {})) for b in rows[:limit]],
                "library": "kutub: books by Sunni authors, works that Shamela lacks and other editions of works it has (sorted by machine and by name lists, not checked book by book); authors are "
                           "named in Latin letters (author_ar where the Arabic name is known); shelf = Shamela's category names, found by machine"}
    return {"matched": len(sel), "passages": int(sum(b["passages"] for b in sel)),
            "books": [{("book" if mk else "shamela_id"): (b["maktaba_id"] if mk else b["shamela_id"]), "title": b.get("title"), "author": b.get("author"),
                       "died_ah": None if b.get("death") is None or b["death"] >= 9000 else b["death"],
                       "category": b.get("cat_name"), "passages": b["passages"]} for b in rows[:limit]]}


# ---- notebook of verified findings (SQLite, ~/semsearch/findings/findings.sqlite3) ----------------------------------------------
FINDINGS = os.environ.get("SEM_FINDINGS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "findings", "findings.sqlite3"))
NB = threading.Lock()


def _finding(con, r):
    import notebook
    return {"id": r["id"], "topic": r["topic"], "tags": notebook.tags_of(con, r["id"]), "shamela_id": r["shamela_id"], "title": r["title"],
            "author": r["author"], "died_ah": r["died_ah"], "part": r["part"], "page": r["page"], "shamela_page_id": r["shamela_page_id"],
            "from": "editor's footnote" if r["kind"] == "f" else "main text", "speaker": r["speaker"], "quotes": r["quotes"] or None,
            "gist": r["gist"], "arabic": r["arabic"], "status": r["status"], "checked_by": r["checked_by"], "checked_at": r["checked_at"]}


def do_findings_search(p):
    import notebook
    with NB:
        con = notebook.connect(FINDINGS)
        try:
            limit = max(1, min(int(p.get("limit") or 20), 100))
            rows = notebook.search(con, tag=p.get("topic") or None, book=(str(p["book"]) if p.get("book") else None), author=p.get("author") or None,
                                   arabic=p.get("arabic") or None, limit=limit)
            total = con.execute("SELECT count(*) FROM findings").fetchone()[0]
            topics = [dict(tag=t, findings=n) for t, n in con.execute("SELECT tag, count(*) FROM tags GROUP BY tag ORDER BY 2 DESC, 1 LIMIT 60")] if p.get("list_topics") else None
            out = {"in_notebook": total, "matched": len(rows), "results": [_finding(con, r) for r in rows]}
            if topics is not None: out["topics"] = topics
            return out
        finally: con.close()


def do_findings_add(p):
    import notebook
    need = [k for k in ("topic", "shamela_id", "part", "page", "arabic", "speaker", "gist") if p.get(k) in (None, "")]
    if need: return {"error": "missing: " + ", ".join(need)}
    s = searcher(); sid = int(p["shamela_id"]); b = next((x for x in s.books if x["shamela_id"] == sid), None)
    if b is None: return {"error": "no book with shamela_id %d in the index" % sid}
    if len(str(p["arabic"]).strip()) < 20: return {"error": "arabic must be the passage's own words as read on the page (at least 20 characters)"}
    death = b.get("death")
    with NB:
        con = notebook.connect(FINDINGS)
        try:
            fid, new = notebook.add(con, str(p["topic"]), sid, int(p["part"]), int(p["page"]), str(p["arabic"]).strip(), tags=p.get("tags") or (),
                                    title=b.get("title") or "", author=b.get("author") or "", died_ah=None if death is None or death >= 9000 else death,
                                    shamela_page_id=p.get("shamela_page_id"), kind="f" if p.get("footnote") else "m", speaker=str(p["speaker"]),
                                    quotes=str(p.get("quotes") or ""), gist=str(p["gist"]), checked_by=str(p.get("checked_by") or "Claude, wording read on the Shamela page"),
                                    status="wording checked on the page by Claude, not yet by a person")
            r = con.execute("SELECT * FROM findings WHERE id=?", (fid,)).fetchone()
            return {"saved": bool(new), "note": None if new else "this page is already in the notebook under this topic; nothing was overwritten (new tags were added)",
                    "finding": _finding(con, r), "in_notebook": con.execute("SELECT count(*) FROM findings").fetchone()[0]}
        finally: con.close()


# ---- the server's own copy of the Shamela pages (pages/pages.sqlite3) -----------------------------------------------------------
def _pages(fn):
    def run(p):
        import pagestore
        con = pagestore.connect()
        try: return fn(pagestore, con, p)
        finally: con.close()
    return run


do_page = _pages(lambda ps, con, p: ps.read(con, p.get("shamela_id"), p.get("page_id"), p.get("part"), p.get("page"), context=p.get("context") or 0,
                                              chars=p.get("chars") or 6000, around=p.get("around") or None))
do_quote = _pages(lambda ps, con, p: ps.check(con, p.get("shamela_id"), str(p.get("quote") or ""), p.get("page_id"), p.get("part"), p.get("page")))
do_contents = _pages(lambda ps, con, p: ps.contents(con, p.get("shamela_id"), p.get("query") or None, limit=max(1, min(int(p.get("limit") or 60), 300))))


# ---- the Kutub pages (kutubstore.py, ~/kutub/index.sqlite3) and the quote check for the owner's own library (library.db) ----------
def do_kutub_page(p):
    import kutubstore
    if not p.get("book"): return {"error": "give book: the Kutub slug (`book` in a search result)"}
    return kutubstore.read(str(p["book"]), idx=p.get("page"), volume=p.get("volume"), page_no=p.get("printed_page"), context=p.get("context") or 0,
                           chars=p.get("chars") or 6000, around=p.get("around") or None)


def do_kutub_quote(p):
    import kutubstore
    if not p.get("book"): return {"error": "give book: the Kutub slug (`book` in a search result)"}
    return kutubstore.check(str(p["book"]), str(p.get("quote") or ""), idx=p.get("page"))


def do_mk_quote(p):
    import kutubstore
    if not p.get("book"): return {"error": "give book: the Maktaba edition id (`book` in a search result, or list_books)"}
    return kutubstore.mk_check(str(p["book"]), str(p.get("quote") or ""), page=p.get("page"))


async def health(request):
    s = STATE["s"]
    return JSONResponse({"ok": True, "loaded": s is not None, "passages": s.N if s else None, "books": len(s.books) if s else None,
                         "error": STATE["error"], "libraries": {"maktaba": os.path.isdir(MK_DIR), "kutub": os.path.isdir(KT_DIR)}})


def handler(fn):
    async def route(request):
        try:
            return JSONResponse(await run_in_threadpool(fn, await request.json()))
        except KeyError as e:
            return JSONResponse({"error": "bad value for an option: %s" % e, "results": []}, status_code=400)
        except semcore.NoVectors as e:
            return JSONResponse({"error": str(e) + ' (semantic_search works there only with mode="keyword")', "results": []}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": repr(e)[:300], "results": []}, status_code=500)
    return route


app = Starlette(routes=[Route("/health", health), Route("/search", handler(do_search), methods=["POST"]),
                        Route("/near", handler(do_near), methods=["POST"]),
                        Route("/digest", handler(do_digest), methods=["POST"]),
                        Route("/books", handler(do_books), methods=["POST"]),
                        Route("/page", handler(do_page), methods=["POST"]), Route("/quote", handler(do_quote), methods=["POST"]),
                        Route("/contents", handler(do_contents), methods=["POST"]),
                        Route("/kutub/page", handler(do_kutub_page), methods=["POST"]), Route("/kutub/quote", handler(do_kutub_quote), methods=["POST"]),
                        Route("/mk/quote", handler(do_mk_quote), methods=["POST"]),
                        Route("/findings/search", handler(do_findings_search), methods=["POST"]),
                        Route("/findings/add", handler(do_findings_add), methods=["POST"])])

if __name__ == "__main__":
    threading.Thread(target=lambda: searcher(), daemon=True).start()   # load in the background so the first search is not slow
    uvicorn.run(app, host=HOST, port=PORT, workers=1, log_level="warning")
