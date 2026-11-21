# -*- coding: utf-8 -*-
"""Step 4 of the Maktaba index: ONE search index for the whole library. The owner's own books (data_maktaba_own, made by mk_assemble.py) and the
imported books are written into a new data_maktaba. The imported books are taken from the data_maktaba of now, where they stand after the own
books; only when it holds none yet (the first merge) from data_kutub. Nothing is cut or embedded again: passages, vectors and page numbers are
taken over as they are; the catalogue fields (title, author, shelf, work, edition) come from the books table of ~/library/library.db, so
register_extra.py must have run first.
   nice -n 10 ~/semsearch/venv/bin/python ~/semsearch/mk/mk_merge.py      then restart the search service
The index of before is kept as data_maktaba.pre-merge (remove it once the new one is checked). Books without vectors (zeros) are listed in
data_maktaba/vec_missing.json. Paths: SEM_HOME, MAKTABA_DB."""
import os, sys, json, zlib, shutil, sqlite3, time
import numpy as np
HOME = os.path.expanduser("~"); SEM = os.environ.get("SEM_HOME", os.path.join(HOME, "semsearch")); sys.path.insert(0, SEM)
import semcore, tantivy
A = os.path.join(SEM, "data_maktaba"); O = A + "_own"; K = os.path.join(SEM, "data_kutub"); TMP = A + ".building"; DIM = semcore.DIM; t0 = time.time()
if not os.path.isdir(O): sys.exit("no data_maktaba_own (the index of the owner's own books): run mk_assemble.py first")
now = json.load(open(os.path.join(A, "books.json"), encoding="utf-8")) if os.path.isdir(A) else []; imp = [b for b in now if b.get("kutub_slug")]
if imp:                                                      # the imported books of the present index: one run of passages at its end
    lo = min(a for b in imp for a, _ in b["ranges"])
    if any(z > lo for b in now if not b.get("kutub_slug") for _, z in b["ranges"]): sys.exit("own and imported passages are mixed in data_maktaba: nothing done")
    SRC = ((O, True, 0, 0), (A, False, lo, 0))               # folder, own books?, first passage taken, added to its book numbers
elif os.path.isdir(K): SRC = ((O, True, 0, 0), (K, False, 0, 1000))
else: sys.exit("no imported books found: neither in data_maktaba nor in data_kutub. Nothing done.")
lib = sqlite3.connect("file:%s?mode=ro" % os.environ.get("MAKTABA_DB", os.path.join(HOME, "library", "library.db")), uri=True); lib.row_factory = sqlite3.Row
cat = {r["id"]: dict(r) for r in lib.execute("SELECT * FROM books")}
try: refs = json.load(open(os.path.join(HOME, "library", "shamela_refs.json"), encoding="utf-8"))
except Exception: refs = {}
shutil.rmtree(TMP, ignore_errors=True); os.makedirs(os.path.join(TMP, "kw"))
sb = tantivy.SchemaBuilder(); sb.add_text_field("t", stored=False, tokenizer_name="whitespace"); sb.add_unsigned_field("id", stored=True, indexed=True, fast=True)
sb.add_unsigned_field("b", stored=False, indexed=True); sb.add_unsigned_field("k", stored=False, indexed=True)
tix = tantivy.Index(sb.build(), path=os.path.join(TMP, "kw")); w = tix.writer(heap_size=1_000_000_000, num_threads=3)
books = []; metas = []; N = 0; buf = []; toff = [0]; tf = open(os.path.join(TMP, "texts.bin"), "wb"); vecs = []; missing = []
for src, own, lo, add in SRC:
    sb_ = [b for b in json.load(open(os.path.join(src, "books.json"), encoding="utf-8")) if own or b.get("kutub_slug")]
    meta = np.array(np.load(os.path.join(src, "meta.npy"))[lo:]); n = len(meta); remap = {}
    for b in sb_:
        bid = b["maktaba_id"] if own else b["kutub_slug"]; c = cat.get(bid)
        if c is None: sys.exit("book %s is in the index %s but not in the catalogue (run register_extra.py first)" % (bid, src))
        nid = b["book_id"] + add; sid = b["shamela_id"]; remap[b["book_id"]] = nid
        if own and nid >= 1000: sys.exit("own book number %d: the numbers from 1000 on belong to the imported books" % nid)
        rng = [[N + a - lo, N + z - lo] for a, z in b["ranges"]]
        e = {"book_id": nid, "shamela_id": sid, "maktaba_id": bid, "title": c["title"], "author": c["author"], "death": b.get("death") if own else c["died"], "cat": 100,
             "kind": c["kind"] or "", "shelf": c["shelf"] or "", "cat_name": "%s | %s" % (c["shelf"] or "", c["kind"] or ""), "edition": c["edition"], "work": c["work"], "primary": int(c["primary_ed"] or 0),
             "ranges": rng, "passages": b["passages"]}
        if not own:
            e["kutub_slug"] = bid; e["author_latin"] = c["author_latin"]; e["author_slug"] = b.get("author_slug")
            if b.get("author_ar"): e["author_ar"] = b["author_ar"]
            if c["shamela_id"]: e["edition_of"] = {"shamela_id": c["shamela_id"], "title": (refs.get(str(c["shamela_id"])) or {}).get("title")}
            if c["note"]: e["flag"] = c["note"]
            if b.get("no_vectors"):
                e["no_vectors"] = True; missing += [{"slug": bid, "from": a, "to": z} for a, z in rng]
        books.append(e)
    meta[:, 0] = np.vectorize(remap.get)(meta[:, 0]); metas.append(meta)
    off = np.load(os.path.join(src, "text_offsets.npy")); i = 0; skip = lo % semcore.BLOCK
    with open(os.path.join(src, "texts.bin"), "rb") as f:
        for k in range(lo // semcore.BLOCK, len(off) - 1):
            f.seek(int(off[k]))
            for t in zlib.decompress(f.read(int(off[k + 1] - off[k]))).decode("utf-8").split("\n"):
                if skip: skip -= 1; continue
                buf.append(t)
                if len(buf) == semcore.BLOCK:
                    z = zlib.compress("\n".join(buf).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z)); buf = []
                d = tantivy.Document(); d.add_text("t", " ".join(semcore.toks(t))); d.add_unsigned("id", N + i); d.add_unsigned("b", int(meta[i, 0])); d.add_unsigned("k", 0); w.add_document(d); i += 1
    assert i == n, (src, i, n)
    vp = os.path.join(src, "vec256.i8"); vecs.append((np.memmap(vp, dtype=np.int8, mode="r", shape=(lo + n, DIM))[lo:] if os.path.exists(vp) else None, n)); N += n
    print("%s: %d books, %d passages (%.0f s)" % (os.path.basename(src), len(sb_), n, time.time() - t0), flush=True)
if buf:
    z = zlib.compress("\n".join(buf).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z))
tf.close(); np.save(os.path.join(TMP, "text_offsets.npy"), np.array(toff, dtype=np.uint64)); np.save(os.path.join(TMP, "meta.npy"), np.concatenate(metas))
X = np.memmap(os.path.join(TMP, "vec256.i8"), dtype=np.int8, mode="w+", shape=(N, DIM)); p = 0
for v, n in vecs:
    if v is not None: X[p:p + n] = v
    p += n
X.flush(); del X
json.dump(books, open(os.path.join(TMP, "books.json"), "w", encoding="utf-8"), ensure_ascii=False); json.dump(missing, open(os.path.join(TMP, "vec_missing.json"), "w", encoding="utf-8"), ensure_ascii=False)
w.commit(); w.wait_merging_threads()
if os.path.isdir(A):
    shutil.rmtree(A + ".pre-merge", ignore_errors=True); os.rename(A, A + ".pre-merge")
os.rename(TMP, A)
s = semcore.Searcher(A, load_model=False)
print("MERGED passages %d | books %d | keyword docs %d | books without vectors %d (%d passages) | %.0f s" % (s.N, len(s.books), s.ks.num_docs, sum(1 for b in books if b.get("no_vectors")), sum(m["to"] - m["from"] for m in missing), time.time() - t0), flush=True)
