"""Quality report for every book in library.db.

Checks: empty pages, missing printed page numbers, gaps in printed numbering, encoding junk,
and (for all books) the share of words found in a reference vocabulary built from the typed books.
For OCR'd books that share is a rough word-accuracy estimate (rare names lower it a little).
"""
import re, sqlite3, sys, pathlib, json
from collections import Counter
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from arabic import norm

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "..").resolve()
con = sqlite3.connect(root / "library.db")
books = {b["id"]: b for b in json.loads((root / "books.json").read_text(encoding="utf-8"))}
ids = [r[0] for r in con.execute("SELECT id FROM books")]
JUNK = re.compile(r"[ÀÃÇÈÌÍÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñ�]")
WORD = re.compile(r"[ء-ي]{2,}")

def words(t):
    return WORD.findall(norm(t))

# reference vocabulary: all typed books except the one being measured (leave-one-out for typed books)
per_book = {i: Counter(w for (t,) in con.execute("SELECT text FROM pages WHERE book=?", (i,)) for w in words(t))
            for i in ids}
typed = [i for i in ids if books[i].get("digital")]
total = Counter()
for i in typed:
    total.update(per_book[i])

results = {}
print(f"{'book':14} {'kind':5} {'pages':>5} {'empty':>5} {'no#':>5} {'gaps':>5} {'junk':>5} {'known%':>7}")
for i in ids:
    rows = con.execute("SELECT page, printed, text FROM pages WHERE book=? ORDER BY page", (i,)).fetchall()
    empty = [p for p, pr, t in rows if len(t.strip()) < 40]
    nonum = sum(1 for p, pr, t in rows if not pr)
    nums = [int(pr.split("/")[-1]) for p, pr, t in rows if pr and pr.split("/")[-1].isdigit()]
    gaps = sum(1 for a, b in zip(nums, nums[1:]) if b - a > 1)
    junk = sum(len(JUNK.findall(t)) for p, pr, t in rows)
    ref = total.copy()
    if i in typed:
        ref.subtract(per_book[i]); ref = +ref
    ws = per_book[i]
    n = sum(ws.values())
    known = sum(c for w, c in ws.items() if w in ref) / n * 100 if n else 0
    kind = "typed" if books[i].get("digital") else "OCR"
    results[i] = {"kind": kind, "pages": len(rows), "empty": len(empty), "gaps": gaps, "known": round(known, 1)}
    print(f"{i:14} {kind:5} {len(rows):5} {len(empty):5} {nonum:5} {gaps:5} {junk:5} {known:7.1f}")

(root / "quality.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
