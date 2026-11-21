# -*- coding: utf-8 -*-
"""After a rebuild of data_kutub: take the vectors of every book that was embedded before from the earlier indexes instead of embedding it again.
A book's passages are cut the same way each time, so its vectors are copied as one block when the passage count is the same.
   ~/semsearch/venv/bin/python ~/semsearch/kutub/kt_carry.py
Earlier indexes looked at, in this order: data_kutub.old (the index of just before), data_kutub.v1 (the first index with vectors, 20 Nov 2026).
Books with no vectors anywhere get zeros (they are found by words, not by meaning), are listed in data_kutub/vec_missing.json and carry
"no_vectors": true in books.json. Embedding them is a separate, paid step (kt_fill.py). Paths: SEM_HOME."""
import os, sys, json
import numpy as np
SEM_HOME = os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch")); NEW = os.path.join(SEM_HOME, "data_kutub"); DIM = 256
src = []
for d in (NEW + ".old", NEW + ".v1"):
    if os.path.exists(os.path.join(d, "vec256.i8")):
        n = int(np.load(os.path.join(d, "meta.npy"), mmap_mode="r").shape[0])
        src.append(({b["kutub_slug"]: b for b in json.load(open(os.path.join(d, "books.json"), encoding="utf-8"))}, np.memmap(os.path.join(d, "vec256.i8"), dtype=np.int8, mode="r", shape=(n, DIM)), d))
if not src: sys.exit("no earlier index with vectors: nothing to carry over")
nb = json.load(open(os.path.join(NEW, "books.json"), encoding="utf-8")); Nn = int(np.load(os.path.join(NEW, "meta.npy"), mmap_mode="r").shape[0])
tmp = os.path.join(NEW, "vec256.i8.tmp"); Xn = np.memmap(tmp, dtype=np.int8, mode="w+", shape=(Nn, DIM)); copied = 0; missing = []; took = {}
for b in nb:
    a, e = b["ranges"][0]; done = False
    for books, X, d in src:
        o = books.get(b["kutub_slug"])
        if o is not None and not o.get("no_vectors") and o["passages"] == b["passages"]:
            oa, oe = o["ranges"][0]; Xn[a:e] = X[oa:oe]; copied += e - a; took[d] = took.get(d, 0) + 1; done = True; break
    if done: b.pop("no_vectors", None)
    else: missing.append({"slug": b["kutub_slug"], "from": a, "to": e}); b["no_vectors"] = True
Xn.flush(); del Xn; os.rename(tmp, os.path.join(NEW, "vec256.i8"))
json.dump(missing, open(os.path.join(NEW, "vec_missing.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump(nb, open(os.path.join(NEW, "books.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("CARRIED vectors of %d passages (%d books; %s) | without vectors: %d passages in %d books -> vec_missing.json"
      % (copied, len(nb) - len(missing), ", ".join("%d from %s" % (v, os.path.basename(k)) for k, v in took.items()), Nn - copied, len(missing)))
