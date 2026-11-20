"""Renumber a typed edition's pages to the PDF pages of a scan of the same edition, so get_page_image works.

Usage: python map_pages.py in.jsonl out.jsonl RULES
RULES: comma-separated "vol:offset[:first-last]" -> pdf = printed + offset for that volume's printed pages
       ("-" as vol for single-volume books). Pages with no rule get numbers after the scan's last page.
Example (Kashf al-Athar): "1:1,2:625"
"""
import json, sys
src, dst, rules = sys.argv[1], sys.argv[2], sys.argv[3]
R = {}
for r in rules.split(","):
    vol, off = r.split(":")[:2]
    R[vol] = int(off)
recs = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
used, out, spare = set(), [], []
for rec in recs:
    pr = str(rec.get("printed") or "")
    vol, _, num = pr.rpartition("/") if "/" in pr else ("-", "", pr)
    if num.isdigit() and vol in R and int(num) + R[vol] not in used:
        rec["page"] = int(num) + R[vol]
        used.add(rec["page"]); out.append(rec)
    else:
        spare.append(rec)
nxt = max(used, default=0) + 1
for rec in spare:          # covers, unnumbered or duplicate pages: keep them, after the mapped range
    rec["page"] = nxt; nxt += 1; out.append(rec)
out.sort(key=lambda r: r["page"])
with open(dst, "w", encoding="utf-8") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"{len(out)} pages: {len(out) - len(spare)} mapped to scan pages, {len(spare)} unmapped (numbered from {max(used, default=0) + 1})")
