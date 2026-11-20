# -*- coding: utf-8 -*-
"""Step 3 of the Maktaba index: put the pieces into ~/semsearch/data_maktaba in the same file formats the big index uses, so
semcore.Searcher can open it:  books.json, meta.npy, vec256.i8, texts.bin + text_offsets.npy, kw/ (tantivy).
   ~/semsearch/venv/bin/python mk_assemble.py"""
import os, sys, json, zlib, shutil
import numpy as np
sys.path.insert(0, os.environ.get("SEM_HOME", os.path.expanduser("~/semsearch")))
import semcore, tantivy
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(os.environ.get("SEM_HOME", os.path.expanduser("~/semsearch")), "data_maktaba"); TMP = OUT + ".building"
rows = np.load(os.path.join(HERE, "rows.npy")); texts = json.load(open(os.path.join(HERE, "texts.json"), encoding="utf-8")); N = len(texts)
books = json.load(open(os.path.join(HERE, "books.json"), encoding="utf-8")); assert len(rows) == N
vecs = [np.frombuffer(open(os.path.join(HERE, "out", f), "rb").read(), dtype=np.int8).reshape(-1, semcore.DIM) for f in sorted(os.listdir(os.path.join(HERE, "out"))) if f.endswith(".i8")]
V = np.concatenate(vecs); assert V.shape == (N, semcore.DIM), (V.shape, N)
shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP)
np.save(os.path.join(TMP, "meta.npy"), rows); json.dump(books, open(os.path.join(TMP, "books.json"), "w", encoding="utf-8"), ensure_ascii=False)
X = np.memmap(os.path.join(TMP, "vec256.i8"), dtype=np.int8, mode="w+", shape=(N, semcore.DIM)); X[:] = V; X.flush(); del X
toff = [0]
with open(os.path.join(TMP, "texts.bin"), "wb") as tf:
    for k in range(0, N, semcore.BLOCK):
        blk = texts[k:k + semcore.BLOCK]; assert all("\n" not in t for t in blk)
        z = zlib.compress("\n".join(blk).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z))
np.save(os.path.join(TMP, "text_offsets.npy"), np.array(toff, dtype=np.uint64))
os.makedirs(os.path.join(TMP, "kw"))
sb = tantivy.SchemaBuilder(); sb.add_text_field("t", stored=False, tokenizer_name="whitespace"); sb.add_unsigned_field("id", stored=True, indexed=True, fast=True)
sb.add_unsigned_field("b", stored=False, indexed=True); sb.add_unsigned_field("k", stored=False, indexed=True)
tix = tantivy.Index(sb.build(), path=os.path.join(TMP, "kw")); w = tix.writer(heap_size=300_000_000, num_threads=2)
for i, t in enumerate(texts):
    d = tantivy.Document(); d.add_text("t", " ".join(semcore.toks(t))); d.add_unsigned("id", i); d.add_unsigned("b", int(rows[i, 0])); d.add_unsigned("k", 0); w.add_document(d)
w.commit(); w.wait_merging_threads()
if os.path.exists(OUT): shutil.rmtree(OUT + ".old", ignore_errors=True); os.rename(OUT, OUT + ".old")
os.rename(TMP, OUT)
s = semcore.Searcher(OUT, load_model=False); t = s.texts([0, N - 1])
print("ASSEMBLED passages", s.N, "books", len(s.books), "| first and last text read back:", t[0][:40], "|", t[N - 1][:40], "| keyword docs", s.ks.num_docs)
