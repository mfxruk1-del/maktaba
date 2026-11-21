# -*- coding: utf-8 -*-
"""Step 1 of the Maktaba index: cut every page of ~/library/library.db into passages exactly as the Shamela build did
(clean(): tags and diacritics off, spaces collapsed; chunk(): about 900 characters with 150 of overlap).
Only the owner's own books: the imported ones (store 'extra') are already in the index and mk_merge.py carries them over.
   ~/semsearch/venv/bin/python mk_prepare.py   -> rows.npy, books.json, texts.json, ship/sNNN.json (passages for the GPU)"""
import sqlite3, json, os, re
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]"); TAG = re.compile(r"<[^>]+>")


def clean(t):
    t = TAG.sub(" ", t or ""); t = TASHKEEL.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def chunk(text, size=900, overlap=150):
    words = text.split(" "); out = []; cur = []; n = 0
    for w in words:
        cur.append(w); n += len(w) + 1
        if n >= size:
            out.append(" ".join(cur)); keep = []; k = 0
            for x in reversed(cur):
                k += len(x) + 1; keep.append(x)
                if k >= overlap: break
            cur = list(reversed(keep)); n = sum(len(x) + 1 for x in cur)
    if cur and (not out or n > overlap + 40): out.append(" ".join(cur))
    return out


con = sqlite3.connect("file:%s?mode=ro" % os.environ.get("MAKTABA_DB", os.path.expanduser("~/library/library.db")), uri=True); con.row_factory = sqlite3.Row
rows = []; texts = []; books = []
for n, b in enumerate(con.execute("SELECT * FROM books WHERE store IS NOT 'extra' ORDER BY id"), 1):
    a = len(rows); m = re.search(r"ت\s*(\d{3,4})", b["author"] or ""); death = int(m.group(1)) if m else None
    for p in con.execute("SELECT page, printed, text FROM pages WHERE book=? ORDER BY page", (b["id"],)):
        try: printed = int(str(p["printed"]).strip())
        except Exception: printed = -1
        for no, t in enumerate(chunk(clean(p["text"]))):
            if len(t) < 20: continue
            rows.append([n, 900000 + n, int(p["page"]), int(p["page"]), -1, printed, 0, no]); texts.append(t)
    if len(rows) > a:
        books.append({"book_id": n, "shamela_id": 900000 + n, "maktaba_id": b["id"], "title": b["title"], "author": b["author"], "death": death, "cat": 100,
                      "cat_name": "Maktaba " + (b["kind"] or ""), "edition": b["edition"], "work": b["work"], "primary": int(b["primary_ed"] or 0),
                      "ranges": [[a, len(rows)]], "passages": len(rows) - a})
np.save(os.path.join(HERE, "rows.npy"), np.asarray(rows, dtype=np.int32)); json.dump(books, open(os.path.join(HERE, "books.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump(texts, open(os.path.join(HERE, "texts.json"), "w", encoding="utf-8"), ensure_ascii=False)
os.makedirs(os.path.join(HERE, "ship"), exist_ok=True)
for f in os.listdir(os.path.join(HERE, "ship")): os.remove(os.path.join(HERE, "ship", f))
for k in range(0, len(texts), 8000): json.dump(texts[k:k + 8000], open(os.path.join(HERE, "ship", "s%03d.json" % (k // 8000)), "w", encoding="utf-8"), ensure_ascii=False)
print("books", len(books), "| passages", len(texts), "| characters", sum(len(t) for t in texts), "| shards", -(-len(texts) // 8000), "| books with a death year", sum(1 for b in books if b["death"]))
