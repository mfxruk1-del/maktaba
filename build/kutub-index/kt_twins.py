# -*- coding: utf-8 -*-
"""The Kutub books whose TEXT the content check found in a Shamela book (~/kutub/overlap_check.json, verdict "same work in Shamela",
made by ~/kutub/overlap_check.py). twins() is the list kt_build.py --skip-twins leaves out of the index (the index in use is built so).
add_to() marks them ("shamela_twin": <shamela_id>) in the books.json of an index that still holds them: the full first-pass index only.
   ~/semsearch/venv/bin/python ~/semsearch/kutub/kt_twins.py        (kt_build.py calls add_to() itself at the end of a build)"""
import os, json

SEM_HOME = os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch")); KUTUB_HOME = os.environ.get("KUTUB_HOME", os.path.join(os.path.expanduser("~"), "kutub"))
CHECK = os.path.join(KUTUB_HOME, "overlap_check.json"); OUT = os.path.join(SEM_HOME, "data_kutub"); SAME = "same work in Shamela"


def twins():
    if not os.path.exists(CHECK): return {}
    return {r["slug"]: r["shamela_id"] for r in json.load(open(CHECK, encoding="utf-8")) if r.get("verdict") == SAME and r.get("shamela_id")}


def add_to(books):
    t = twins(); n = 0
    for b in books:
        if b.get("kutub_slug") in t: b["shamela_twin"] = t[b["kutub_slug"]]; n += 1
        else: b.pop("shamela_twin", None)
    return n


if __name__ == "__main__":
    p = os.path.join(OUT, "books.json"); books = json.load(open(p, encoding="utf-8")); n = add_to(books)
    json.dump(books, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False); os.replace(p + ".tmp", p)
    print("shamela_twin on %d of %d books (%d passages of %d)" % (n, len(books), sum(b["passages"] for b in books if b.get("shamela_twin")), sum(b["passages"] for b in books)))
