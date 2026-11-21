# -*- coding: utf-8 -*-
"""The page texts of the imported books (the ones ~/kutub/sort_decide.py kept) -> ~/library/texts_extra.db, a read-only store beside library.db.
   ~/library/maktaba-venv/bin/python ~/library/import_extra.py
pages(book, page, printed, text): book = the book's id in books.json, page = running page number as in the source file (from 0), printed = "volume/page" when known.
pages_words: whole-word index over the normalised text (same normalisation as library.db), rowid = the row of pages.
The source file is opened read-only and never written. Run again to rebuild the store from nothing (the old one is replaced at the end)."""
import os, sys, json, time, sqlite3
HOME = os.path.expanduser("~"); LIB = os.path.join(HOME, "library"); sys.path.insert(0, os.path.join(LIB, "maktaba"))
from arabic import norm
SRC = "file:%s?mode=ro&immutable=1" % os.environ.get("KUTUB_DB", os.path.join(HOME, "kutub", "index.sqlite3"))
keep = [d for d in json.load(open(os.path.join(HOME, "kutub", "sorted.json"), encoding="utf-8")) if d.get("keep")]
out = os.path.join(LIB, "texts_extra.db"); tmp = out + ".tmp"
if os.path.exists(tmp): os.remove(tmp)
src = sqlite3.connect(SRC, uri=True); con = sqlite3.connect(tmp)
con.executescript("""PRAGMA page_size=8192; PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
CREATE TABLE pages(book TEXT, page INTEGER, printed TEXT, text TEXT, PRIMARY KEY(book, page));
CREATE VIRTUAL TABLE pages_words USING fts5(norm, content='', tokenize='unicode61');
CREATE TABLE info(key TEXT PRIMARY KEY, value TEXT);""")
t0 = time.time(); n = 0; chars = 0
for i, d in enumerate(sorted(keep, key=lambda d: d["slug"]), 1):
    for idx, vol, pno, text in src.execute("SELECT idx, volume, page_no, text FROM pages WHERE slug=? ORDER BY idx", (d["slug"],)):
        text = text or ""; pr = None
        if isinstance(pno, int) and pno >= 0: pr = ("%d/%d" % (vol, pno)) if isinstance(vol, int) and vol > 0 else str(pno)
        cur = con.execute("INSERT INTO pages VALUES (?,?,?,?)", (d["slug"], int(idx), pr, text))
        con.execute("INSERT INTO pages_words(rowid, norm) VALUES (?,?)", (cur.lastrowid, norm(text))); n += 1; chars += len(text)
    if i % 200 == 0: con.commit(); print("%d of %d books | %d pages | %d characters | %.0f s" % (i, len(keep), n, chars, time.time() - t0), flush=True)
con.execute("INSERT INTO info VALUES ('built', ?), ('books', ?), ('pages', ?)", (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), str(len(keep)), str(n)))
con.commit(); con.execute("INSERT INTO pages_words(pages_words) VALUES ('optimize')"); con.commit(); con.close()
os.replace(tmp, out)
print("EXTRA_DONE books %d pages %d characters %d | %.1f GB | %.0f s" % (len(keep), n, chars, os.path.getsize(out) / 1e9, time.time() - t0), flush=True)
