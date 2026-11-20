# -*- coding: utf-8 -*-
"""Copy every Shamela book's pages (and table of contents) from the Hugging Face dataset AuthenticIlm/Shamela4_Full_DB into
pages.sqlite3 on this server, so pages can be read and quotes checked without the owner's PC.
   ~/semsearch/venv/bin/python ingest.py plan       -> how many files and bytes there are to fetch (nothing is written)
   nohup nice -n 10 ~/semsearch/venv/bin/python ingest.py run > ingest.log 2>&1 &     -> resumable: a book already stored is skipped
The page text is stored exactly as the dataset gives it (body and footnotes apart), zlib-compressed. Ids are the dataset's:
page_id (running number inside the book) and shamela_page_id (the id the Shamela tools use)."""
import os, sys, json, re, time, zlib, sqlite3, tempfile, shutil, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__)); DB = os.path.join(HERE, "pages.sqlite3"); REPO = "AuthenticIlm/Shamela4_Full_DB"
os.environ.pop("HF_HUB_OFFLINE", None)
from huggingface_hub import HfApi, hf_hub_download

SCHEMA = """
CREATE TABLE IF NOT EXISTS books(shamela_id INTEGER PRIMARY KEY, book_id INTEGER, folder TEXT, title TEXT, author TEXT, death INTEGER, cat TEXT,
  pages INTEGER, bytes INTEGER, toc_entries INTEGER, meta BLOB, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS pages(shamela_id INTEGER NOT NULL, page_id INTEGER NOT NULL, shamela_page_id INTEGER, part INTEGER, page_num INTEGER,
  body BLOB, foot BLOB, PRIMARY KEY(shamela_id, page_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_pages_sp ON pages(shamela_id, shamela_page_id);
CREATE INDEX IF NOT EXISTS ix_pages_pp ON pages(shamela_id, part, page_num);
CREATE TABLE IF NOT EXISTS toc(shamela_id INTEGER PRIMARY KEY, data BLOB);
"""


def to_int(v, d=-1):
    try: return int(v)
    except Exception: return d


def listing():
    files = {}
    for x in HfApi().list_repo_tree(REPO, repo_type="dataset", recursive=True):
        p = getattr(x, "path", ""); size = getattr(x, "size", None)
        if size is None or "/" not in p: continue
        folder, name = p.rsplit("/", 1)
        if name in ("pages.jsonl", "toc.jsonl", "book_metadata.json"): files.setdefault(folder, {})[name] = size
    return files


def fetch(folder, names, tmp):
    out = {}
    for n in names:
        for attempt in (1, 2, 3):
            try:
                out[n] = hf_hub_download(REPO, folder + "/" + n, repo_type="dataset", local_dir=tmp); break
            except Exception as e:
                if attempt == 3: raise
                time.sleep(5 * attempt)
    return out


def one(b, folder, names):
    tmp = tempfile.mkdtemp(prefix="pg_", dir=os.path.join(HERE, "tmp"))
    try:
        f = fetch(folder, names, tmp); rows = []; raw = 0
        with open(f["pages.jsonl"], encoding="utf-8") as fh:
            for line in fh:
                if not line.strip(): continue
                d = json.loads(line); body = d.get("body") or ""; foot = d.get("footnotes") or ""
                if not isinstance(body, str): body = json.dumps(body, ensure_ascii=False)
                if not isinstance(foot, str): foot = json.dumps(foot, ensure_ascii=False)
                raw += len(body) + len(foot)
                rows.append((b["shamela_id"], to_int(d.get("page_id")), to_int(d.get("shamela_page_id")), to_int(d.get("part")), to_int(d.get("page_num")),
                             zlib.compress(body.encode("utf-8"), 6), zlib.compress(foot.encode("utf-8"), 6) if foot else None))
        toc = None; n_toc = 0
        if "toc.jsonl" in f:
            t = open(f["toc.jsonl"], "rb").read(); n_toc = t.count(b"\n"); toc = zlib.compress(t, 6)
        meta = zlib.compress(open(f["book_metadata.json"], "rb").read(), 6) if "book_metadata.json" in f else None
        return b, folder, rows, raw, toc, n_toc, meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(cmd):
    books = {b["book_id"]: b for b in json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "books.json"), encoding="utf-8"))}
    files = listing(); todo = []; unknown = 0; total = 0
    for folder, names in files.items():
        if "pages.jsonl" not in names: continue
        m = re.match(r"(\d+)__", folder.rsplit("/", 1)[-1]); b = books.get(int(m.group(1))) if m else None
        if b is None: unknown += 1; continue
        todo.append((b, folder, names)); total += sum(names.values())
    print("folders with pages:", len(todo), "| not in the index's book list:", unknown, "| bytes to fetch: %.1f GB" % (total / 2**30),
          "| with a toc:", sum(1 for _, _, n in todo if "toc.jsonl" in n), flush=True)
    if cmd == "plan": return
    os.makedirs(os.path.join(HERE, "tmp"), exist_ok=True)
    con = sqlite3.connect(DB); con.executescript(SCHEMA); con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
    have = {r[0] for r in con.execute("SELECT shamela_id FROM books")}; todo = [t for t in todo if t[0]["shamela_id"] not in have]
    todo.sort(key=lambda t: t[2].get("pages.jsonl", 0)); print("already stored:", len(have), "| to do:", len(todo), flush=True)
    t0 = time.time(); done = 0; got = 0; failed = []
    with ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(one, b, folder, [n for n in names if n != "book_metadata.json"]): (b, folder) for b, folder, names in todo}   # two files a book: fewer requests under the Hub rate limit
        for fu in as_completed(futs):
            b0, folder0 = futs[fu]
            try: b, folder, rows, raw, toc, n_toc, meta = fu.result()
            except Exception as e:
                failed.append(b0["shamela_id"]); print("FAILED", b0["shamela_id"], folder0, repr(e)[:160], flush=True); continue
            con.executemany("INSERT OR REPLACE INTO pages VALUES(?,?,?,?,?,?,?)", rows)
            if toc is not None: con.execute("INSERT OR REPLACE INTO toc VALUES(?,?)", (b["shamela_id"], toc))
            con.execute("INSERT OR REPLACE INTO books VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (b["shamela_id"], b["book_id"], folder, b.get("title"), b.get("author"), b.get("death"),
                        b.get("cat_name"), len(rows), raw, n_toc, meta, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())))
            con.commit(); done += 1; got += raw
            if done % 100 == 0: print("%d of %d books | %.1f GB of text | %.0f s | failed %d" % (done, len(todo), got / 2**30, time.time() - t0, len(failed)), flush=True)
    n = con.execute("SELECT count(*), sum(pages) FROM books").fetchone()
    print("INGEST_DONE books %s pages %s | this run %d books, failed %d %s | %.0f s" % (n[0], n[1], done, len(failed), failed[:20], time.time() - t0), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
