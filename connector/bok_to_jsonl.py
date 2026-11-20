"""Convert a Shamela .bok (MS Access) book to Maktaba jsonl (pure Python: pip install access-parser).

Each body row (table b<id>) is one printed page: {"page": running n, "printed": "page" or "part/page", "text"}.
Prints the book card (Betaka) so the edition can be recorded.
Usage: python bok_to_jsonl.py book.bok output.jsonl
"""
import json, re, sys
from access_parser import AccessParser

def fix(s):
    """access-parser reads the Windows-1256 text of old .bok files as Latin-1; undo that."""
    if not isinstance(s, str):
        return "" if s is None else str(s)
    try:
        return s.encode("latin-1").decode("cp1256")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s                      # already proper Unicode

bok, dst = sys.argv[1], sys.argv[2]
db = AccessParser(bok)
body = next(t for t in db.catalog if re.fullmatch(r"b\d+", t))
t = {k.lower(): v for k, v in db.parse_table(body).items()}
card = fix(db.parse_table("Main")["Betaka"][0]).strip()
n = len(t["nass"])
rows = sorted(range(n), key=lambda i: t["id"][i])
part = lambda i: fix(t["part"][i]).strip() if "part" in t else ""
parts = {part(i) for i in range(n)} - {""}
numeric = {p for p in parts if p.isdigit()}
multi = len(numeric) > 1                       # a multi-volume book: label pages "vol/page"
pages, last = [], None
for i in rows:
    pr = t["page"][i] if "page" in t else None
    pr = "" if pr in (None, "") else str(pr)
    pt = part(i)
    if pt and not pt.isdigit():
        label = f"{pt}/{pr}" if pr else pt      # named sections such as المقدمة or الغلاف
    else:
        label = f"{pt}/{pr}" if multi and pr else pr
    text = fix(t["nass"][i]).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(l.strip() for l in text.split("\n") if l.strip())
    if pages and label and label == last:
        pages[-1]["text"] += "\n" + text          # several rows on one printed page
    else:
        pages.append({"page": len(pages) + 1, "printed": label or None, "text": text})
    last = label
with open(dst, "w", encoding="utf-8") as out:
    for p in pages:
        out.write(json.dumps(p, ensure_ascii=False) + "\n")
print(card)
print(f"-> {len(pages)} pages, printed {pages[0]['printed']}..{pages[-1]['printed']}, parts={sorted(parts)}")
