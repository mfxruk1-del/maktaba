"""Build library.db from books.json: one row per page, Arabic-normalised full-text index.

Usage: python build_index.py [library_dir]
books.json: [{"id", "title", "author", "edition", "source", "jsonl", "img", "digital", "segments"}]
  jsonl: {"page": n, "text": "..."} per line (output of ocr_book.sh), or {"page", "printed", "text"}
         for digital texts that already know their printed page (openiti_to_jsonl.py, bok_to_jsonl.py)
  img:   optional folder of page scans named p0001.png ... (for verification)
  digital: true for typed texts (no OCR page-number guessing)
  segments: optional [[first_pdf, last_pdf, "vol"], ...] when several volumes share one PDF
"""
import json, re, sqlite3, sys, pathlib
from collections import Counter
from arabic import norm

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
books = json.loads((root / "books.json").read_text(encoding="utf-8"))
db_path = root / "library.db"
tmp = root / "library.db.tmp"
tmp.unlink(missing_ok=True)

con = sqlite3.connect(tmp)
con.executescript("""
CREATE TABLE books(id TEXT PRIMARY KEY, title TEXT, author TEXT, edition TEXT, source TEXT,
                   img TEXT, pages INTEGER, work TEXT, work_title TEXT, kind TEXT, primary_ed INTEGER);
CREATE TABLE pages(book TEXT, page INTEGER, printed TEXT, text TEXT, norm TEXT,
                   PRIMARY KEY(book, page));
CREATE VIRTUAL TABLE pages_words USING fts5(norm, content='pages', content_rowid='rowid',
                                            tokenize='unicode61');
CREATE VIRTUAL TABLE pages_fts USING fts5(norm, content='pages', content_rowid='rowid',
                                          tokenize='trigram');
""")

# printed page number = a short last line like "(٤٥)", "45", "(أ)", "( ب )"
PRINTED = re.compile(r"^\(?\s*([0-9٠-٩]{1,4}|[ء-يـ]{1,3})\s*\)?$")

DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

for b in books:
    recs = []
    for line in (root / b["jsonl"]).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        text = rec["text"].strip()
        if rec.get("printed"):        # digital texts carry their printed page already
            recs.append([rec["page"], str(rec["printed"]), text])
            continue
        printed = None
        lines = [l.strip() for l in text.splitlines()]
        for t in list(reversed(lines[-2:])) + lines[:1]:   # bottom of page first, then a top-line number like "(١٤٣)"
            m = PRINTED.match(t)
            if m:
                printed = m.group(1).translate(DIGITS)
                break
        recs.append([rec["page"], printed, text])

    # OCR'd page numbers are patchy; the offset between PDF page and printed page is usually constant
    # over the main text, so take the most common offset and apply it across the range where it holds.
    # "segments": [[first_pdf, last_pdf, "vol"], ...] for several volumes in one PDF (page numbers restart).
    segs = b.get("segments") or [[1, 10**6, ""]]
    for s_lo, s_hi, vol in ([] if b.get("digital") else segs):
        seg = [r for r in recs if s_lo <= r[0] <= s_hi]
        offsets = Counter(p - int(pr) for p, pr, _ in seg if pr and pr.isdigit())
        if not offsets:
            continue
        off, votes = offsets.most_common(1)[0]
        agree = [p for p, pr, _ in seg if pr and pr.isdigit() and p - int(pr) == off]
        if votes >= 5:
            lo, hi = min(agree), max(agree)
            for r in seg:
                if lo <= r[0] <= hi:
                    r[1] = (f"{vol}/" if vol else "") + str(r[0] - off)
            print(f"{b['id']}{' vol ' + vol if vol else ''}: printed = pdf - {off} for pdf pages {lo}-{hi} ({votes} pages agreed)")

    for p, pr, text in recs:
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?)", (b["id"], p, pr, text, norm(text)))
    n = len(recs)
    con.execute("INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (b["id"], b["title"], b.get("author"), b.get("edition"), b.get("source"),
                 b.get("img"), n, b.get("work", b["id"]), b.get("work_title", b["title"]),
                 "typed" if b.get("digital") else "OCR", int(bool(b.get("primary")))))
    print(f"{b['id']}: {n} pages")

con.execute("INSERT INTO pages_fts(pages_fts) VALUES ('rebuild')")
con.execute("INSERT INTO pages_words(pages_words) VALUES ('rebuild')")   # whole-word index for mode word/near
con.commit()
con.close()
tmp.replace(db_path)
print("wrote", db_path)
