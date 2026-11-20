# -*- coding: utf-8 -*-
"""Tests for the Kutub library and the per-library functions: a side copy of the service (SIDE, port 8792) against the live one (LIVE, 8791).
   ~/semsearch/venv/bin/python ~/semsearch/tests/kutub_test.py          prints PASS / FAIL per test; exit code 1 when any test fails
   After an install: SIDE=http://127.0.0.1:8791 ... (the a-tests then compare the service with itself, b to n test the install).
Read-only: it only sends searches (nothing is saved anywhere). Paths: SEM_HOME (default ~/semsearch), MAKTABA_DB (default
~/library/library.db), SEM_CONNECTOR / LIVE_CONNECTOR (the connector file under test and the one to compare its size with).
(a) regression: the same request with `library` unset gives the same JSON on both services (timing fields "ms" left out)
(b) Kutub nearby-words: rows have the Kutub shape and each top row's page opens through /kutub/page and holds the words
(c) /kutub/quote finds a real 6-word run and refuses it with one word changed
(d) /digest with library "maktaba" and "kutub" returns lines
(e) /mk/quote finds a run copied from a library.db page
(f) /search with library "kutub" gives the clear no-vectors error, and the service keeps answering
(g)-(o) extras: labels and author filters in Kutub, the vectors belong to their passages, Maktaba searched whole by default, /books, a category outside Shamela and a page
        read with no page are refused in plain words, the connector end to end."""
import os, re, sys, json, sqlite3, inspect, urllib.request, urllib.error, importlib.util
sys.dont_write_bytecode = True                                   # the test imports live files to compare with: it must not write beside them

HOME = os.path.expanduser("~"); SEM_HOME = os.environ.get("SEM_HOME", os.path.join(HOME, "semsearch"))
LIVE = os.environ.get("LIVE", "http://127.0.0.1:8791"); SIDE = os.environ.get("SIDE", "http://127.0.0.1:8792")
MAKTABA_DB = os.environ.get("MAKTABA_DB", os.path.join(HOME, "library", "library.db"))
LIVE_CONNECTOR = os.environ.get("LIVE_CONNECTOR", os.path.join(HOME, "library", "maktaba", "sem_tools.py"))
SEM_CONNECTOR = os.environ.get("SEM_CONNECTOR") or LIVE_CONNECTOR            # name a side copy of sem_tools.py here to test it before installing
sys.path.insert(0, SEM_HOME)
import semcore                                                   # only for toks(): how the index reads a word
RESULTS = []
_VEC = []


def has_vectors():
    """True when the Kutub index of the service under test has vectors (a meaning-search there answers instead of refusing)."""
    if not _VEC: _VEC.append(post(SIDE, "/search", {"query": "حكم الشرب قائما", "library": "kutub", "limit": 1})[0] == 200)
    return _VEC[0]


def post(base, path, payload, timeout=400):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode("utf-8"))
        except Exception: return e.code, {}


def no_ms(x):
    if isinstance(x, dict): return {k: no_ms(v) for k, v in x.items() if k != "ms"}
    if isinstance(x, list): return [no_ms(v) for v in x]
    return x


def report(name, ok, line):
    RESULTS.append(ok); print("%s  %s: %s" % ("PASS" if ok else "FAIL", name, line), flush=True)


def test(name):
    def deco(fn):
        try:
            ok, line = fn()
        except Exception as e:
            ok, line = False, "the test itself broke: %r" % (e,)
        report(name, ok, line)
        return fn
    return deco


NEAR = [{"phrases": ["الشرب قائما"]},
        {"phrases": ["نكاح المتعة", "متعة النساء"], "category": "الفقه الحنفي", "limit": 10},
        {"phrases": ["رؤية الهلال"], "author": "ابن تيمية", "sort": "oldest"},
        {"phrases": ["الأنبياء|الرسل أحياء قبورهم|قبور"], "window": 6, "footnotes": "include", "sort": "mixed", "per_book": 1},
        {"phrases": ["حاضر ناظر", "علم الغيب"], "shamela_ids": [21613], "group": False, "preset": "all"}]
SEARCH = [{"query": "حكم الشرب قائما"},
          {"query": "نكاح المتعة", "category": "الفقه الحنفي", "limit": 5},
          {"query": "رؤية الهلال في بلد هل تلزم أهل بلد آخر", "queries": ["اختلاف المطالع"], "author": "ابن عابدين"},
          {"query": "التوسل بالأنبياء", "mode": "keyword", "preset": "all", "footnotes": "only"},
          {"query": "قطع الصلاة لإنقاذ غريق", "shamela_ids": [21613], "mode": "meaning", "chars": 200}]
DIGEST = [{"phrases": ["الشرب قائما"], "queries": ["حكم الشرب قائما"], "scopes": ["hanafi"]},
          {"phrases": ["نكاح المتعة"], "queries": ["حكم نكاح المتعة"], "scopes": ["four"], "books": 5},
          {"phrases": ["رؤية الهلال", "اختلاف المطالع"], "scopes": ["author:ابن تيمية", "aqida;before:700"]},
          {"queries": ["حياة الأنبياء في قبورهم"], "scopes": ["books:21613,5423"], "items": True},
          {"phrases": ["الاستواء العرش"], "queries": ["معنى الاستواء على العرش"], "footnotes": "include", "chars": 200}]
BOOKS = [{"author": "ابن عابدين"}, {"title": "الهداية", "category": "الفقه الحنفي", "limit": 5}]


def regression(path, reqs):
    def run():
        bad = []; sizes = []
        for n, p in enumerate(reqs, 1):
            sa, a = post(LIVE, path, p); sb, b = post(SIDE, path, p); a, b = no_ms(a), no_ms(b)
            sizes.append(len(json.dumps(a, ensure_ascii=False)))
            if sa != sb or a != b:
                keys = [k for k in set(a) | set(b) if a.get(k) != b.get(k)] if isinstance(a, dict) and isinstance(b, dict) else ["?"]
                bad.append("request %d differs (status %s / %s, in: %s)" % (n, sa, sb, ", ".join(sorted(keys))[:120]))
            elif sa != 200 or (path != "/books" and not (a.get("results") or a.get("digest"))): bad.append("request %d: nothing came back to compare (status %s)" % (n, sa))
        return (not bad), ("%d requests, library unset, same JSON on %s and %s (answer sizes %s characters)" % (len(reqs), LIVE[-4:], SIDE[-4:], sizes)) if not bad else "; ".join(bad)
    return run


test("a1 regression /near")(regression("/near", NEAR))
test("a2 regression /search")(regression("/search", SEARCH))
test("a3 regression /digest")(regression("/digest", DIGEST))
test("a4 regression /books (extra)")(regression("/books", BOOKS))

TOP = {}                                                         # the top Kutub row of each question, kept for (c)


def words_on(text, phrase):
    have = set(semcore.toks(text))
    return all(any(t in have for a in w.split("|") for t in semcore.toks(a)) for w in phrase.split())


for q in ("الشرب قائما", "نكاح المتعة", "رؤية الهلال"):
    @test("b  Kutub /near «%s»" % q)
    def _(q=q):
        st, r = post(SIDE, "/near", {"phrases": [q], "library": "kutub", "limit": 10})
        rows = r.get("results") or []
        if st != 200 or not rows: return False, "status %s, %d rows, error %s" % (st, len(rows), r.get("error"))
        shape = [x for x in rows if not (x.get("library") == "kutub" and isinstance(x.get("book"), str) and isinstance(x.get("page"), int) and x.get("title")
                                         and "printed_page" in x and "volume" in x and "shamela_id" not in x and "shamela_page_id" not in x)]
        if shape: return False, "%d of %d rows do not have the Kutub shape, first: %s" % (len(shape), len(rows), json.dumps(shape[0], ensure_ascii=False)[:200])
        note = str(r.get("library"))
        if "kutub_read_page" not in note or "machine-read" not in note or "no school or sect" not in note: return False, "the note on how to open a result and on whose books these are is missing"
        if '"also_in_shamela"' in json.dumps(r) or "twin" in note: return False, "twin wording is still in the answer"
        top = rows[0]; st2, pg = post(SIDE, "/kutub/page", {"book": top["book"], "page": top["page"], "chars": 20000})
        page = next((x for x in pg.get("pages", []) if x.get("asked_for")), None)
        if st2 != 200 or page is None: return False, "the top row's page did not open: status %s %s" % (st2, str(pg.get("error"))[:120])
        if not words_on(page["text"], q): return False, "page %s of %s opened but does not hold the words" % (top["page"], top["book"])
        TOP[q] = (top, page)
        return True, "%s hits in %s books; %d rows, all Kutub-shaped; top row %s page %d (%s) opens and holds the words" % (
            r.get("total_hits"), r.get("books_with_hits"), len(rows), top["book"], top["page"], (top.get("title") or "")[:40])


def six_words(text, skip=12):
    w = [x for x in text.split() if re.search("[ء-ي]{2,}", x)]
    for i in range(min(skip, max(0, len(w) - 6)), max(1, len(w) - 5)):
        run = w[i:i + 6]
        if " ".join(run) in " ".join(text.split()) and len({semcore.norm(x) for x in run}) == 6: return run
    return None


@test("c  /kutub/quote finds a real 6-word run, refuses it with one word changed")
def _():
    if not TOP: return False, "no Kutub page from (b) to copy from"
    top, page = next(iter(TOP.values())); run = six_words(page["text"])
    if not run: return False, "no clean 6-word run on page %s of %s" % (top["page"], top["book"])
    good = " ".join(run); bad = " ".join(run[:2] + ["زمخشريات"] + run[3:])
    s1, a = post(SIDE, "/kutub/quote", {"book": top["book"], "quote": good, "page": top["page"]})
    s2, b = post(SIDE, "/kutub/quote", {"book": top["book"], "quote": bad, "page": top["page"]})
    s3, c = post(SIDE, "/kutub/quote", {"book": top["book"], "quote": good})
    s4, d = post(SIDE, "/kutub/quote", {"book": top["book"], "quote": bad})
    if not (a.get("found") is True and a.get("page") == top["page"]): return False, "the real run was not found on its page: %s" % json.dumps(a, ensure_ascii=False)[:200]
    if b.get("found") is not False: return False, "the changed run was accepted on the page: %s" % json.dumps(b, ensure_ascii=False)[:200]
    if not (c.get("found") is True and any(p.get("page") == top["page"] for p in c.get("places", []))): return False, "whole-book check did not find the real run"
    if d.get("found") is not False: return False, "whole-book check accepted the changed run"
    return True, "«%s» found on page %d of %s (and by the whole-book check); with word 3 changed: not found, longest run %s of 6" % (
        good, top["page"], top["book"], (b.get("closest") or {}).get("longest_run_of_words"))


@test("d1 /digest library maktaba returns lines")
def _():
    st, r = post(SIDE, "/digest", {"library": "maktaba", "phrases": ["أبي حنيفة الفقه", "مناقب الإمام"], "queries": ["فضل أبي حنيفة في الفقه"]})
    lines = [l for l in (r.get("digest") or "").split("\n") if re.match(r"\d+\. ", l)]
    ok = st == 200 and lines and all(re.search(r"\| book \S+ page \d+", l) for l in lines) and "get_page" in r["digest"].split("\n")[-1]
    return bool(ok), "%d book lines, each ending in «book <id> page <n>»; first: %s" % (len(lines), lines[0][:150]) if ok else "status %s error %s digest %s" % (st, r.get("error"), (r.get("digest") or "")[:200])


@test("d2 /digest library kutub returns lines (and says so when it ran on nearby-words alone)")
def _():
    st, r = post(SIDE, "/digest", {"library": "kutub", "phrases": ["الشرب قائما", "شرب قائما"], "queries": ["حكم الشرب قائما"], "scopes": [None, "before:600"]})
    dg = (r.get("digest") or "").split("\n"); lines = [l for l in dg if re.match(r"\d+\. ", l)]
    ok = st == 200 and lines and all(re.search(r"\| book \S+ page \d+", l) for l in lines) and (("nearby-words alone" in dg[0]) != has_vectors()) and "kutub_read_page" in dg[-1] and "no school or sect" in dg[-1] and "in-shamela" not in r["digest"] and len(r.get("scopes", [])) == 2
    return bool(ok), "%d book lines in 2 scopes; first line: «%s»; a line: %s" % (len(lines), dg[0][:110], lines[0][:140]) if ok else "status %s error %s digest %s" % (st, r.get("error"), "\n".join(dg)[:300])


@test("d3 /digest library kutub refuses a category scope with a clear message (extra)")
def _():
    st, r = post(SIDE, "/digest", {"library": "kutub", "phrases": ["الشرب قائما"], "scopes": ["hanafi"]})
    return st == 400 and "no categories" in str(r.get("error")), "status %s: %s" % (st, str(r.get("error"))[:140])


@test("e  /mk/quote finds a run copied from a library.db page")
def _():
    con = sqlite3.connect("file:%s?mode=ro" % MAKTABA_DB, uri=True)
    for book, page, text in con.execute("SELECT book, page, text FROM pages WHERE length(text) > 900 ORDER BY book, page LIMIT 400 OFFSET 150"):
        run = six_words(text)
        if run: break
    else: return False, "no page with a clean 6-word run in library.db"
    good = " ".join(run); bad = " ".join(run[:2] + ["زمخشريات"] + run[3:])
    s1, a = post(SIDE, "/mk/quote", {"book": book, "quote": good, "page": page}); s2, b = post(SIDE, "/mk/quote", {"book": book, "quote": bad, "page": page})
    s3, c = post(SIDE, "/mk/quote", {"book": book, "quote": good})
    ok = a.get("found") is True and a.get("page") == page and b.get("found") is False and c.get("found") is True
    return ok, "«%s» found in %s page %d (and by the whole-book check); changed run refused" % (good, book, page) if ok else json.dumps([a, b, c], ensure_ascii=False)[:300]


@test("f  /search library kutub: by meaning when the index has vectors, else the clear no-vectors error; no crash")
def _():
    st, r = post(SIDE, "/search", {"query": "حكم الشرب قائما", "library": "kutub"})
    st2, r2 = post(SIDE, "/search", {"query": "الشرب قائما", "library": "kutub", "mode": "keyword", "limit": 3})
    h = json.loads(urllib.request.urlopen(SIDE + "/health", timeout=20).read().decode("utf-8"))
    if has_vectors(): ok = st == 200 and len(r.get("results") or []) > 0 and r["results"][0].get("library") == "kutub" and h.get("loaded") is True
    else: ok = st == 400 and "no meaning-search for this library yet" in str(r.get("error")) and "nearby_words" in str(r.get("error")) and h.get("loaded") is True
    ok2 = st2 == 200 and len(r2.get("results") or []) == 3 and r2["results"][0].get("library") == "kutub"
    return ok and ok2, "vectors: %s; status %s, %s; the service still answers; mode=keyword works there (%d rows)" % (
        has_vectors(), st, "%d rows by meaning" % len(r.get("results") or []) if st == 200 else "error «%s»" % r.get("error"), len(r2.get("results") or []))


@test("g  labels in Kutub: pages of an author on the label list carry author_note (extra)")
def _():
    try: labs = json.load(open(os.path.join(SEM_HOME, "labels.json"), encoding="utf-8")).get("labels", [])
    except Exception: labs = []
    slugs = {x for l in labs for x in (l.get("kutub_slugs") or [])}
    if not slugs: return True, "skipped: labels.json names no author of this library (kutub_slugs)"
    st, bk = post(SIDE, "/books", {"library": "kutub", "limit": 3000}); books = [b for b in (bk.get("books") or []) if b.get("author_slug") in slugs]
    if not books: return True, "skipped: no book of a labelled author in this index"
    big = max(books, key=lambda b: b.get("passages") or 0)
    st, r = post(SIDE, "/near", {"phrases": ["في ذلك", "قال في", "على ان", "من ذلك"], "window": 8, "library": "kutub", "books": [big["book"]], "limit": 8})
    rows = r.get("results") or []; noted = [x for x in rows if x.get("author_note")]
    ok = st == 200 and rows and len(noted) == len(rows)
    return bool(ok), ("%d books of labelled authors in the index; in the largest of them %d of %d rows carry author_note" % (len(books), len(noted), len(rows))
                      if ok else "status %s rows %d labelled %d error %s" % (st, len(rows), len(noted), r.get("error")))


@test("h  Kutub scoped to one book by slug, and an unknown author gives a clear error (extra)")
def _():
    if not TOP: return False, "no Kutub row from (b)"
    top, _p = next(iter(TOP.values())); q = next(iter(TOP))
    st, r = post(SIDE, "/near", {"phrases": [q], "library": "kutub", "books": [top["book"]]})
    st2, r2 = post(SIDE, "/near", {"phrases": [q], "library": "kutub", "author": "zzzz qqqq"})
    ok = st == 200 and (r.get("scope") or {}).get("books") == 1 and all(x.get("book") == top["book"] for x in r.get("results", [])) and r.get("results") and "no Kutub author" in str(r2.get("error"))
    return bool(ok), "books=[%s]: scope of 1 book, %d rows, all from it; unknown author: «%s»" % (top["book"], len(r.get("results", [])), str(r2.get("error"))[:70])


@test("i  Maktaba is searched whole by default (preset \"auto\" as the connector sends it) (extra)")
def _():
    p = {"phrases": ["أبي حنيفة"], "library": "maktaba", "preset": "auto", "limit": 5}
    st, r = post(SIDE, "/near", p); st0, r0 = post(LIVE, "/near", p)
    st1, r1 = post(SIDE, "/near", dict(p, preset="classical"))
    n = (r.get("scope") or {}).get("books"); n0 = (r0.get("scope") or {}).get("books"); n1 = (r1.get("scope") or {}).get("books")
    lab = any(x.get("library") == "maktaba" and x.get("book") for x in r.get("results", []))
    return st == 200 and n == 38 and lab and n1 is not None and n1 < 38, "side copy: %s books in scope (all 38); live today with the same request: %s books; preset \"classical\" by name still narrows it (%s)" % (n, n0, n1)


@test("j  /books library kutub (extra)")
def _():
    st, r = post(SIDE, "/books", {"library": "kutub", "limit": 3}); st2, r2 = post(SIDE, "/books", {"library": "kutub", "author": "ابن تيمية", "limit": 3})
    b = (r.get("books") or [{}])[0]
    ok = st == 200 and r.get("matched", 0) > 2000 and isinstance(b.get("book"), str) and "shamela_id" not in b and st2 == 200 and r2.get("matched", 0) > 0
    return bool(ok), "%s books, %s passages in the Kutub index; largest: %s (%s passages); by «ابن تيمية»: %s books" % (r.get("matched"), r.get("passages"), b.get("book"), b.get("passages"), r2.get("matched"))


@test("m  a category outside Shamela is refused in plain words on /near and /search (extra)")
def _():
    out = []
    for path, p in (("/near", {"phrases": ["الشرب قائما"]}), ("/search", {"query": "الشرب قائما", "mode": "keyword"})):
        st, r = post(SIDE, path, dict(p, library="kutub", category="الفقه الحنفي")); out.append(st == 400 and "has no categories" in str(r.get("error")))
        mk = {"phrases": ["أبي حنيفة"]} if path == "/near" else {"query": "أبي حنيفة", "mode": "keyword"}
        st, r = post(SIDE, path, dict(mk, library="maktaba", category="الفقه الحنفي")); out.append(st == 400 and "typed" in str(r.get("error")))
        st, r = post(SIDE, path, dict(mk, library="maktaba", category="ocr")); out.append(st == 200 and bool(r.get("results")) and all(x.get("text_kind") == "OCR" for x in r["results"]))
        st, r = post(SIDE, path, dict(p, library="kutub")); out.append(st == 200 and bool(r.get("results")))
    st, r = post(SIDE, "/near", {"phrases": ["الشرب قائما"], "library": "kutub", "category": "x"})
    return all(out), "kutub + category: 400 «%s»; maktaba + a Shamela category: 400; maktaba + \"ocr\": OCR books only; no category: rows (checks %s)" % (str(r.get("error"))[:105], "".join("1" if x else "0" for x in out))


@test("n  /kutub/page with no page says so instead of returning page 1 (extra)")
def _():
    if not TOP: return False, "no Kutub row from (b)"
    top, _p = next(iter(TOP.values()))
    st, r = post(SIDE, "/kutub/page", {"book": top["book"]}); st2, r2 = post(SIDE, "/kutub/page", {"book": top["book"], "volume": 1})
    st3, r3 = post(SIDE, "/kutub/page", {"book": top["book"], "page": top["page"]})
    ok = "give page" in str(r.get("error")) and "pages" not in r and "give page" in str(r2.get("error")) and len(r3.get("pages", [])) == 1
    return ok, "no page: «%s»; volume alone: the same; with the page: it opens" % str(r.get("error"))[:90]


@test("k  the connector end to end: its tools called against the service (extra)")
def _():
    os.environ["MAKTABA_SEM_URL"] = SIDE

    class Fake:
        def __init__(self): self.tools = {}
        def tool(self, **kw):
            def deco(fn): self.tools[fn.__name__] = fn; return fn
            return deco

    def tools_of(path, name):
        spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        f = Fake(); m.register(f); return f.tools
    t = tools_of(SEM_CONNECTOR, "sem_tools_under_test"); live = tools_of(LIVE_CONNECTOR, "sem_tools_live")
    need = ["search_digest", "semantic_search", "nearby_words", "semantic_books", "kutub_read_page", "check_quote", "shamela_read_page", "shamela_check_quote", "shamela_contents", "findings_search", "findings_add"]
    miss = [n for n in need if n not in t]
    if miss: return False, "tools missing: %s" % miss
    docs = "".join(fn.__doc__ or "" for fn in t.values()); size = lambda d: sum(len(fn.__doc__ or "") for fn in d.values())
    stale = [w for w in ("new_only", "also_in_shamela", "twin", "in-shamela") if w in docs] + [n for n in t if "new_only" in inspect.signature(t[n]).parameters]
    if stale: return False, "twin wording or the new_only parameter is still in the tools: %s" % stale
    r = t["nearby_words"](["الشرب قائما"], library="kutub", limit=3); row = (r.get("results") or [{}])[0]
    pg = t["kutub_read_page"](row.get("book"), page=row.get("page"), around="الشرب قائما") if row.get("book") else {}
    text = next((x for x in pg.get("pages", []) if x.get("asked_for")), {}).get("text", ""); run = six_words(text, skip=3)
    ck = t["check_quote"]("kutub", row.get("book"), " ".join(run), page=row.get("page")) if run else {}
    dg = t["search_digest"](phrases=["الشرب قائما"], library="kutub", books=3)
    one = t["nearby_words"](["الشرب قائما"], library="kutub", books=[row.get("book")], limit=3) if row.get("book") else {}
    e1 = t["check_quote"]("shamela", "x", "a b c"); e2 = t["semantic_search"]("حكم الشرب قائما", library="kutub"); e3 = t["nearby_words"](["الشرب قائما"], library="nope")
    e4 = t["kutub_read_page"](row.get("book"))
    ok = (row.get("library") == "kutub" and text and ck.get("found") is True and (dg.startswith("Kutub library: no meaning-search") != has_vectors()) and "book " in dg
          and (one.get("scope") or {}).get("books") == 1 and "error" in e1 and ((len(e2.get("results") or []) > 0) if has_vectors() else ("no meaning-search" in str(e2.get("error")))) and "error" in e3 and "give page" in str(e4.get("error")))
    return bool(ok), "%d tools (live: %d); nearby_words -> kutub_read_page -> check_quote found «%s»; search_digest(library=kutub) gives lines; books=[slug] narrows to 1 book; bad library names and a page read with no page are refused; no twin wording; TOOL DESCRIPTIONS %d characters (live: %d)" % (
        len(t), len(live), " ".join(run or [])[:50], size(t), size(live))


@test("o  Kutub vectors belong to their passages: a whole passage, searched by meaning, brings its own page back (extra)")
def _():
    if not has_vectors(): return True, "skipped: this Kutub index has no vectors"
    st, bk = post(SIDE, "/books", {"library": "kutub", "limit": 3000}); books = bk.get("books") or bk.get("results") or []
    if len(books) < 50: return False, "/books gave %d books" % len(books)
    pick = [books[i] for i in (0, len(books) // 7, 2 * len(books) // 7, 3 * len(books) // 7, 4 * len(books) // 7, 5 * len(books) // 7, 6 * len(books) // 7, len(books) - 2)]
    hit = 0; tried = 0; notes = []
    for b in pick:
        slug = b.get("book") or b.get("kutub_slug")
        st, r = post(SIDE, "/near", {"library": "kutub", "phrases": ["في ذلك", "قال في", "على ان", "من ذلك"], "window": 8, "books": [slug], "limit": 1, "chars": 900, "group": False})
        row = (r.get("results") or [None])[0]
        if not row or len(row.get("text") or "") < 200: continue
        tried += 1; q = " ".join((row.get("text") or "").replace("«", " ").replace("»", " ").replace("…", " ").split())      # the whole passage: its own vector should be the nearest one
        st2, r2 = post(SIDE, "/search", {"library": "kutub", "query": q, "mode": "meaning", "limit": 3, "chars": 80})
        top = [(x.get("book"), x.get("page")) for x in (r2.get("results") or [])]
        ok1 = any(bb == slug and abs((pp or 0) - (row.get("page") or 0)) <= 1 for bb, pp in top); hit += ok1
        notes.append("%s p%s %s" % (slug[:28], row.get("page"), "back in top 3" if ok1 else "NOT back: %s" % top[:1]))
    return tried >= 5 and hit >= tried - 1, "%d of %d passages came back in the top 3 by meaning alone, over the whole library; %s" % (hit, tried, "; ".join(notes))


print("\n%d of %d tests passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
