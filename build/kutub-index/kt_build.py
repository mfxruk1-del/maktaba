# -*- coding: utf-8 -*-
"""Keyword index for the Kutub works that Shamela lacks (no GPU, no vectors): ~/semsearch/data_kutub, same file formats as
data/ and data_maktaba/ but WITHOUT vec256.i8.

   nice -n 10 ~/semsearch/venv/bin/python ~/semsearch/kutub/kt_build.py --skip-twins      (6 minutes; this is how the index in use was built)
   ... kt_build.py                every catalogue book that is not in Shamela BY TITLE (4,727 books, 15 minutes): the first pass
   ... kt_build.py --sorted       exactly the books kept by ~/kutub/sort_decide.py (sorted.json): the index in use since the evening of 20 Nov 2026
   ... kt_build.py --project      only print the projected sizes and stop
The order from nothing: ~/kutub/catalog.py (titles) -> kt_build.py (full index) -> ~/kutub/overlap_check.py (which of those books have their
text in Shamela under another title: 1,975 on 20 Nov 2026) -> kt_build.py --skip-twins (2,751 books, 2,296,918 passages).
Paths: SEM_HOME (default ~/semsearch), KUTUB_HOME (default ~/kutub: catalog.json, overlap_check.json), KUTUB_DB (default
KUTUB_HOME/index.sqlite3), SEM_CODE (another folder to take semcore.py from).

Source: ~/kutub/index.sqlite3 (opened read-only + immutable, never written), books chosen by ~/kutub/catalog.json (in_shamela = false).
Each page -> clean() -> chunk() EXACTLY as mk/mk_prepare.py does (the two functions are taken from that file's own source at run time:
900 characters, 150 overlap), passages under 20 characters dropped.
STREAMS: three worker processes cut the pages (1,500 pages a job, at most 10 jobs in flight), the main process writes texts.bin block by
block, meta rows to a raw file and the tantivy documents as they arrive; no step holds all texts.
Output (first in data_kutub.building, renamed at the end):
  books.json  book_id n, shamela_id 2000000+n, kutub_slug, title (Arabic, else Latin), author (Latin transliteration), author_slug,
              death (Kutub's year; None when missing or after 1448 = Kutub's mark for a living author), cat 200, cat_name "Kutub", ranges, passages
              + pages, maybe_shamela_id (catalogue: probably in Shamela under a longer/shorter title), author_ar (kt_authors.py, where known)
  meta.npy    int32 [N,8]: book_id, shamela_id, idx, idx, volume or -1, page_no or -1, 0, chunk_no        (same columns as mk_prepare)
  texts.bin + text_offsets.npy   zlib blocks of semcore.BLOCK passages joined by "\n"                       (as mk_assemble)
  kw/         tantivy, same schema as mk_assemble, text = " ".join(semcore.toks(passage)); heap 1 GB, 3 threads
Stops before starting when the projected peak would leave less than 24 GB free on / ."""
import os, sys, json, zlib, time, shutil, sqlite3, random, subprocess, collections
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); HOME = os.path.expanduser("~")
SEM_HOME = os.environ.get("SEM_HOME", os.path.join(HOME, "semsearch")); KUTUB_HOME = os.environ.get("KUTUB_HOME", os.path.join(HOME, "kutub"))
sys.path.insert(0, os.environ.get("SEM_CODE") or SEM_HOME)
import semcore

KUTUB = "file:%s?mode=ro&immutable=1" % os.environ.get("KUTUB_DB", os.path.join(KUTUB_HOME, "index.sqlite3"))
CATALOG = os.path.join(KUTUB_HOME, "catalog.json")
OUT = os.path.join(SEM_HOME, "data_kutub"); TMP = OUT + ".building"
SID0 = 2000000; NOW_AH = 1448; FLOOR_GB = 24; STEP = 1500; WINDOW = 10; WORKERS = 3
I32 = 2 ** 31 - 1

# clean() and chunk() from mk_prepare.py itself (importing that file would run the Maktaba build, so only this slice of its source is run)
_src = open(os.path.join(SEM_HOME, "mk", "mk_prepare.py"), encoding="utf-8").read()
_a = _src.index("TASHKEEL = "); _b = _src.index("con = sqlite3.connect")
assert "def clean(t):" in _src[_a:_b] and "def chunk(text, size=900, overlap=150):" in _src[_a:_b]
_ns = {"re": __import__("re")}; exec(_src[_a:_b], _ns); clean = _ns["clean"]; chunk = _ns["chunk"]

_CON = None


def _con():
    global _CON
    if _CON is None: _CON = sqlite3.connect(KUTUB, uri=True)
    return _CON


def _i32(v):
    return int(v) if isinstance(v, int) and -1 <= v <= I32 else -1


def work(job):
    """One job = up to STEP pages of one book -> (n, meta rows, passages, their keyword text, pages read, characters read)."""
    n, slug, lo, hi = job
    rows = []; texts = []; tk = []; pages = 0; chars = 0
    for idx, vol, pno, text in _con().execute("SELECT idx, volume, page_no, text FROM pages WHERE slug=? AND idx>=? AND idx<? ORDER BY idx", (slug, lo, hi)):
        pages += 1; chars += len(text or "")
        for no, t in enumerate(chunk(clean(text))):
            if len(t) < 20: continue
            rows.append((n, SID0 + n, int(idx), int(idx), _i32(vol), _i32(pno), 0, no)); texts.append(t); tk.append(" ".join(semcore.toks(t)))
    return n, np.asarray(rows, dtype=np.int32).reshape(-1, 8), texts, tk, pages, chars


def free_gb():
    return int(subprocess.check_output(["df", "-B1G", "--output=avail", "/"]).split()[-1])


def say(*a):
    print(time.strftime("%H:%M:%S", time.gmtime()), "UTC |", *a, flush=True)


def todo():
    """The catalogue's books that are not in Shamela by title. With --skip-twins (the owner's decision of 20 Nov 2026) also without the books
    whose text the content check found in Shamela (overlap_check.json): 2,752 books stay, the 1,975 left out are listed in that file."""
    cat = json.load(open(CATALOG, encoding="utf-8")); skip = set()
    if "--sorted" in sys.argv:                               # exactly the books that sort_decide.py kept (KUTUB_HOME/sorted.json), each with its shelf and its work
        srt = {d["slug"]: d for d in json.load(open(os.path.join(KUTUB_HOME, "sorted.json"), encoding="utf-8")) if d.get("keep")}
        return sorted((dict(r, _sorted=srt[r["slug"]]) for r in cat if r["slug"] in srt), key=lambda r: r["slug"])
    if "--skip-twins" in sys.argv:
        sys.path.insert(0, HERE); import kt_twins; skip = set(kt_twins.twins())
    return sorted((r for r in cat if not r["in_shamela"] and r["slug"] not in skip), key=lambda r: r["slug"])


def project(books):
    """Cut a random sample (60 books, first 400 pages each) and scale by the catalogue's character counts."""
    rnd = random.Random(20261120); sample = rnd.sample(books, min(60, len(books))); con = _con()
    t0 = time.time(); ch = 0; ps = 0; zb = 0; buf = []
    for r in sample:
        for (text,) in con.execute("SELECT text FROM pages WHERE slug=? ORDER BY idx LIMIT 400", (r["slug"],)):
            ch += len(text or "")
            for t in chunk(clean(text)):
                if len(t) < 20: continue
                ps += 1; buf.append(t); semcore.toks(t)
                if len(buf) == semcore.BLOCK: zb += len(zlib.compress("\n".join(buf).encode("utf-8"), 6)); buf = []
    if buf: zb += len(zlib.compress("\n".join(buf).encode("utf-8"), 6))
    dt = time.time() - t0; total = sum(r["chars"] or 0 for r in books); k = total / max(ch, 1)
    passages = int(ps * k); texts = zb * k; kw = texts * (3851631706 / 3986176875)        # kw : texts.bin as in the Shamela index
    meta = passages * 32; final = texts + kw + meta; peak = texts + 2 * kw + 2 * meta    # tantivy needs room for its merges
    free = free_gb()
    say("PROJECTION from %d sample books (%d characters, %d passages, %.0f s): books to index %d | characters %d" % (len(sample), ch, ps, dt, len(books), total))
    say("  passages about %d | texts.bin %.2f GB | kw %.2f GB | meta.npy %.2f GB | final %.2f GB | peak while building %.2f GB"
        % (passages, texts / 1e9, kw / 1e9, meta / 1e9, final / 1e9, peak / 1e9))
    say("  free disk now %d GB | free at the peak about %.1f GB | free at the end about %.1f GB | floor %d GB" % (free, free - peak / 2 ** 30, free - final / 2 ** 30, FLOOR_GB))
    say("  one process cut %.1f million characters a second: with %d workers the build should take about %.0f minutes" % (ch / dt / 1e6, WORKERS, total / (ch / dt) / WORKERS / 60 * 1.5))
    return free - peak / 2 ** 30 >= FLOOR_GB


def main():
    import tantivy
    books = todo(); t0 = time.time()
    if not project(books):
        say("STOP: the build would leave less than %d GB free. Nothing was written." % FLOOR_GB); sys.exit(2)
    if "--project" in sys.argv: return
    shutil.rmtree(TMP, ignore_errors=True); os.makedirs(os.path.join(TMP, "kw"))
    con = _con(); info = {}

    def jobs():
        for n, r in enumerate(books, 1):
            lo, hi = con.execute("SELECT min(idx), max(idx) FROM pages WHERE slug=?", (r["slug"],)).fetchone()
            info[n] = r
            if lo is None: yield (n, r["slug"], 0, 0); continue
            for a in range(lo, hi + 1, STEP): yield (n, r["slug"], a, min(a + STEP, hi + 1))

    ex = ProcessPoolExecutor(WORKERS, mp_context=mp.get_context("spawn")); it = jobs(); pending = collections.deque()

    def fill():
        while len(pending) < WINDOW:
            j = next(it, None)
            if j is None: return
            pending.append(ex.submit(work, j))

    fill()
    sb = tantivy.SchemaBuilder(); sb.add_text_field("t", stored=False, tokenizer_name="whitespace"); sb.add_unsigned_field("id", stored=True, indexed=True, fast=True)
    sb.add_unsigned_field("b", stored=False, indexed=True); sb.add_unsigned_field("k", stored=False, indexed=True)
    tix = tantivy.Index(sb.build(), path=os.path.join(TMP, "kw")); w = tix.writer(heap_size=1_000_000_000, num_threads=3)
    metaf = open(os.path.join(TMP, "meta.raw"), "wb"); tf = open(os.path.join(TMP, "texts.bin"), "wb"); toff = [0]; buf = []
    N = 0; out = []; cur = None; start = 0; done = 0; pages = 0; chars = 0; empty = 0

    def close_book():
        nonlocal done, empty
        if cur is None: return
        r = info.pop(cur); done += 1
        if N > start:
            y = r.get("year"); b = {"book_id": cur, "shamela_id": SID0 + cur, "kutub_slug": r["slug"], "title": (r.get("title_arabic") or "").strip() or r.get("title") or r["slug"],
                                    "author": r.get("author"), "author_slug": r.get("author_slug"), "death": y if isinstance(y, int) and 0 < y <= NOW_AH else None,
                                    "cat": 200, "cat_name": "Kutub", "pages": r.get("pages_done"), "ranges": [[start, N]], "passages": N - start}
            if r.get("maybe_shamela_id"): b["maybe_shamela_id"] = r["maybe_shamela_id"]
            d = r.get("_sorted")
            if d:
                b["cat_name"] = d.get("shelf") or "Kutub"; b["sorted_as"] = d.get("why")
                for k in ("edition_of", "shares_text_with", "new_share", "flag", "own_library_work"):
                    if d.get(k) is not None: b[k] = d[k]
            out.append(b)
        else: empty += 1
        if done % 500 == 0:
            el = time.time() - t0; fr = free_gb()
            say("books %d / %d | passages %d | pages %d | characters %d | %.0f min elapsed, about %.0f min left | free disk %d GB"
                % (done, len(books), N, pages, chars, el / 60, el / done * (len(books) - done) / 60, fr))
            if fr < FLOOR_GB:
                say("STOP: free disk fell under %d GB. The unfinished folder %s is left as it is; delete it to get the space back." % (FLOOR_GB, TMP)); os._exit(3)

    while pending:
        n, rows, texts, tk, pg, chn = pending.popleft().result(); fill()
        if n != cur:
            close_book(); cur = n; start = N
        pages += pg; chars += chn
        if len(rows): metaf.write(rows.tobytes())
        for t, k in zip(texts, tk):
            buf.append(t)
            if len(buf) == semcore.BLOCK:
                z = zlib.compress("\n".join(buf).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z)); buf = []
            d = tantivy.Document(); d.add_text("t", k); d.add_unsigned("id", N); d.add_unsigned("b", n); d.add_unsigned("k", 0); w.add_document(d); N += 1
    close_book(); ex.shutdown()
    if buf:
        z = zlib.compress("\n".join(buf).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z))
    tf.close(); metaf.close()
    say("all pages cut: books with text %d (no text: %d) | passages %d | pages %d | characters %d | committing the keyword index" % (len(out), empty, N, pages, chars))
    np.save(os.path.join(TMP, "text_offsets.npy"), np.array(toff, dtype=np.uint64))
    meta = np.fromfile(os.path.join(TMP, "meta.raw"), dtype=np.int32).reshape(-1, 8); assert len(meta) == N, (len(meta), N)
    assert len(toff) - 1 == -(-N // semcore.BLOCK) and sum(b["passages"] for b in out) == N
    np.save(os.path.join(TMP, "meta.npy"), meta); del meta; os.remove(os.path.join(TMP, "meta.raw"))
    sys.path.insert(0, HERE); import kt_authors, kt_twins
    say("shamela_twin (text found in Shamela by overlap_check.py; none when the twins were left out) put on %d books" % kt_twins.add_to(out))
    say("Arabic author names (from the catalogue's matched pairs) put on %d of %d books" % (kt_authors.add_to(out), len(out)))
    json.dump(out, open(os.path.join(TMP, "books.json"), "w", encoding="utf-8"), ensure_ascii=False)
    w.commit(); w.wait_merging_threads()
    if os.path.exists(OUT): shutil.rmtree(OUT + ".old", ignore_errors=True); os.rename(OUT, OUT + ".old")
    os.rename(TMP, OUT)
    s = semcore.Searcher(OUT, load_model=False); tx = s.texts([0, N - 1])
    say("BUILT passages", s.N, "| books", len(s.books), "| keyword docs", s.ks.num_docs, "| vectors:", "none (keyword-only)" if s.X is None else "present",
        "| first and last text read back:", tx[0][:60], "|", tx[N - 1][:60])
    r = s.near(["صلاة الجمعة"], window=3, preset="all", limit=2, chars=120)
    say("nearby-words smoke test: total_hits", r.get("total_hits"), "| books_with_hits", r.get("books_with_hits"), "| first:", json.dumps((r.get("results") or [None])[0], ensure_ascii=False)[:400])
    sz = lambda p: sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    say("SIZES texts.bin %.2f GB | kw %.2f GB | meta.npy %.2f GB | whole folder %.2f GB | build time %.0f min | free disk now %d GB"
        % (os.path.getsize(os.path.join(OUT, "texts.bin")) / 1e9, sz(os.path.join(OUT, "kw")) / 1e9, os.path.getsize(os.path.join(OUT, "meta.npy")) / 1e9, sz(OUT) / 1e9,
           (time.time() - t0) / 60, free_gb()))
    say("KT_BUILD_DONE")


if __name__ == "__main__":
    main()
