# -*- coding: utf-8 -*-
"""Arabic author names for the Kutub index. Kutub gives its authors in Latin transliteration only; but every Kutub book that the
catalogue matched to a Shamela book (~/kutub/catalog.json, in_shamela) pairs a Kutub author_slug with Shamela's Arabic name for that
author. arabic_names() takes, for each slug, the Arabic name most of its matched books carry; a slug whose leading name holds less
than two thirds of its matches is left out.
   ~/semsearch/venv/bin/python ~/semsearch/kutub/kt_authors.py      adds "author_ar" to ~/semsearch/data_kutub/books.json where known
(kt_build.py calls add_to() itself at the end of a build). Used for: author filters given in Arabic, labels by Arabic name, display."""
import os, json, collections

SEM_HOME = os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch")); KUTUB_HOME = os.environ.get("KUTUB_HOME", os.path.join(os.path.expanduser("~"), "kutub"))
CATALOG = os.path.join(KUTUB_HOME, "catalog.json"); SHAMELA = os.path.join(SEM_HOME, "data", "books.json"); OUT = os.path.join(SEM_HOME, "data_kutub")


def arabic_names():
    sh = {b["shamela_id"]: b for b in json.load(open(SHAMELA, encoding="utf-8"))}; votes = collections.defaultdict(collections.Counter)
    for r in json.load(open(CATALOG, encoding="utf-8")):
        if r.get("in_shamela") and r.get("author_slug") and r.get("shamela_id") in sh:
            a = (sh[r["shamela_id"]].get("author") or "").strip()
            if a and a != "-": votes[r["author_slug"]][a] += 1
    out = {}
    for slug, c in votes.items():
        name, n = c.most_common(1)[0]
        if n * 3 >= sum(c.values()) * 2: out[slug] = name
    return out


def add_to(books):
    """Put "author_ar" on the book records (in place) where the slug's Arabic name is known. Returns how many got one."""
    names = arabic_names(); n = 0
    for b in books:
        a = names.get(b.get("author_slug"))
        if a: b["author_ar"] = a; n += 1
        else: b.pop("author_ar", None)
    return n


if __name__ == "__main__":
    p = os.path.join(OUT, "books.json"); books = json.load(open(p, encoding="utf-8")); n = add_to(books)
    json.dump(books, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False); os.replace(p + ".tmp", p)
    print("author_ar on %d of %d books (%d author slugs have a known Arabic name)" % (n, len(books), len(arabic_names())))
