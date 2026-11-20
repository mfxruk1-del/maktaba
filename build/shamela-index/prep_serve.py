# -*- coding: utf-8 -*-
# Step D: turn the embedded shards into the files the server needs, then test them through the server's own search code.
# Reads  shamela-sem:/emb, /index/meta.npy, /index/shard_offsets.json, /manifest.json
# Writes shamela-sem:/serve/  books.json meta.npy vec256.i8 texts.bin text_offsets.npy kw/ selftest.json
import gzip, json, os, shutil, time, zlib

BLOCK = 256


def tok_shard2(path):
    import semcore
    with gzip.open(path[:-4] + ".txt.gz", "rt", encoding="utf-8") as g: lines = g.read().split("\n")[:-1]
    return lines, [" ".join(semcore.toks(x)) for x in lines]


def build_serve(emb_dir, index_dir, manifest_path, out_dir, tok_procs=14, log=print):
    import numpy as np, tantivy
    from multiprocessing import Pool
    os.makedirs(out_dir, exist_ok=True); T0 = time.time()
    meta = np.load(os.path.join(index_dir, "meta.npy")); N = len(meta)
    so = json.load(open(os.path.join(index_dir, "shard_offsets.json"))); offs = so["offsets"]
    files = [os.path.join(emb_dir, f) for f in so["files"]]
    np.save(os.path.join(out_dir, "meta.npy"), meta)
    # books and where their passages sit
    b = meta[:, 0]; change = np.flatnonzero(np.diff(b) != 0) + 1
    starts = np.concatenate([[0], change]); ends = np.concatenate([change, [N]]); ranges = {}
    for s, e in zip(starts, ends): ranges.setdefault(int(b[s]), []).append([int(s), int(e)])
    man = json.load(open(manifest_path, encoding="utf-8"))["books"]; books = []
    for x in man:
        try: bid = int(x["book_id"])
        except Exception: continue
        if bid not in ranges: continue
        cat_dir = x["path"].split("/")[0]; death = x.get("death")
        try: death = int(death) if death not in (None, "") else None
        except Exception: death = None
        books.append({"book_id": bid, "shamela_id": int(x["shamela_id"]) if str(x.get("shamela_id") or "").isdigit() else -1,
                      "title": x.get("title"), "author": x.get("author"), "death": death, "cat": x.get("cat"),
                      "cat_name": cat_dir.split("__", 1)[-1].replace("-", " "), "ranges": ranges[bid],
                      "passages": int(sum(e - s for s, e in ranges[bid]))})
    json.dump(books, open(os.path.join(out_dir, "books.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log("books with passages", len(books), "of", len(man), "| books split over several ranges", sum(1 for x in books if len(x["ranges"]) > 1))
    # short vectors, one byte per number
    X = np.memmap(os.path.join(out_dir, "vec256.i8"), dtype=np.int8, mode="w+", shape=(N, 256))
    for k, f in enumerate(files):
        E = np.load(f).astype(np.float32)[:, :256]
        if len(E):
            n = np.linalg.norm(E, axis=1, keepdims=True); n[n == 0] = 1
            X[offs[k]:offs[k] + len(E)] = np.clip(np.rint(E / n * 127), -127, 127).astype(np.int8)
        if k % 40 == 0: log("vectors", k + 1, "/", len(files), round(time.time() - T0), "s")
    X.flush(); del X
    # passage texts (compressed blocks) and the keyword index, in one pass
    kw_dir = os.path.join(out_dir, "kw"); shutil.rmtree(kw_dir, ignore_errors=True); os.makedirs(kw_dir, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    tp = ThreadPoolExecutor(8)
    sb = tantivy.SchemaBuilder(); sb.add_text_field("t", stored=False, tokenizer_name="whitespace")
    sb.add_unsigned_field("id", stored=True, indexed=True, fast=True)
    sb.add_unsigned_field("b", stored=False, indexed=True); sb.add_unsigned_field("k", stored=False, indexed=True)
    tix = tantivy.Index(sb.build(), path=kw_dir); w = tix.writer(heap_size=3_000_000_000, num_threads=8)
    tf = open(os.path.join(out_dir, "texts.bin"), "wb"); toff = [0]; buf = []; gid = 0
    with Pool(tok_procs) as pool:
        for k, (lines, tk) in enumerate(pool.imap(tok_shard2, files, chunksize=1)):
            if len(lines) != offs[k + 1] - offs[k]: raise RuntimeError("text rows mismatch in " + files[k])
            for line, t in zip(lines, tk):
                d = tantivy.Document(); d.add_text("t", t); d.add_unsigned("id", gid)
                d.add_unsigned("b", int(meta[gid, 0])); d.add_unsigned("k", int(meta[gid, 6])); w.add_document(d); gid += 1
            buf += lines; nb = len(buf) // BLOCK
            for z in tp.map(lambda j: zlib.compress("\n".join(buf[j * BLOCK:(j + 1) * BLOCK]).encode("utf-8"), 6), range(nb)):
                tf.write(z); toff.append(toff[-1] + len(z))
            del buf[:nb * BLOCK]
            if k % 40 == 0: log("texts + keyword index", k + 1, "/", len(files), round(time.time() - T0), "s")
    if buf:
        z = zlib.compress("\n".join(buf).encode("utf-8"), 6); tf.write(z); toff.append(toff[-1] + len(z))
    tf.close(); np.save(os.path.join(out_dir, "text_offsets.npy"), np.array(toff, dtype=np.uint64))
    w.commit(); w.wait_merging_threads(); tix.reload()
    if tix.searcher().num_docs != N or gid != N: raise RuntimeError("keyword index has %d docs, expected %d" % (tix.searcher().num_docs, N))
    sizes = {}
    for root, _, fs in os.walk(out_dir):
        for f in fs: sizes[os.path.relpath(root, out_dir).split(os.sep)[0] if root != out_dir else f] = sizes.get(os.path.relpath(root, out_dir).split(os.sep)[0] if root != out_dir else f, 0) + os.path.getsize(os.path.join(root, f))
    log("sizes GB", {k: round(v / 1e9, 2) for k, v in sizes.items()}, "| passages", gid, "| total s", round(time.time() - T0))
    return {"n": gid, "sizes_gb": {k: round(v / 1e9, 2) for k, v in sizes.items()}}


def selftest(out_dir, gold, log=print):
    """Run the gold questions through the server's own search code."""
    import semcore
    S = semcore.Searcher(out_dir); res = {}
    def rank(ids, g):
        for r, i in enumerate(ids, 1):
            m = S.meta[i]
            if m[0] == g[1] and m[4] == g[2] and abs(int(m[5]) - g[3]) <= 1: return r
        return None
    for g in gold:
        b = S.by_id.get(g[1])
        if not b: res[g[0]] = "book missing"; continue
        r1 = S.search(g[4], shamela_ids=[b["shamela_id"]], limit=3)
        r2 = S.search(g[4], author=b["author"], limit=3) if b.get("author") else None
        res[g[0]] = {"book": rank(r1["fused_ids"], g), "book_ms": r1["ms"]["total"], "book_passages": r1["scope"]["passages"],
                     "author": rank(r2["fused_ids"], g) if r2 else None, "author_books": r2["scope"]["books"] if r2 else None,
                     "author_ms": r2["ms"]["total"] if r2 else None}
        log("SELF", g[0], json.dumps(res[g[0]]))
    r = S.search(gold[2][4], limit=3); res["_open_ms"] = r["ms"]; log("SELF open search ms", json.dumps(r["ms"]))
    r = S.search(gold[2][4], category="الفقه الحنفي", died_before=1300, footnotes="exclude", limit=3)
    res["_filtered"] = {"scope": r["scope"], "ms": r["ms"], "top": [[x["title"], x["part"], x["page"]] for x in r["results"]]}
    log("SELF filtered", json.dumps(res["_filtered"], ensure_ascii=False))
    json.dump(res, open(os.path.join(out_dir, "selftest.json"), "w"), ensure_ascii=False)
    return res

# --- modal ---
if os.environ.get("SEM_LOCAL") != "1":
    import modal

    app = modal.App("shamela-serve-prep")
    vol = modal.Volume.from_name("shamela-sem")
    image = (modal.Image.debian_slim(python_version="3.11")
             .pip_install("torch", "transformers", "sentence-transformers", "numpy", "tantivy")
             .env({"HF_HOME": "/data/hf"})
             .add_local_python_source("semcore")
             .add_local_file("build_index.py", "/root/bi_src.py"))

    @app.function(image=image, volumes={"/data": vol}, cpu=16, memory=32000, timeout=3 * 3600)
    def prep():
        def log(*a): print(*a, flush=True)
        H = {}; exec(open("/root/bi_src.py", encoding="utf-8").read().split("# --- modal ---")[0], H)
        work = "/tmp/serve"; shutil.rmtree(work, ignore_errors=True)
        out = build_serve("/data/emb", "/data/index", "/data/manifest.json", work, log=log)
        shutil.rmtree("/data/serve", ignore_errors=True); t = time.time(); shutil.copytree(work, "/data/serve"); vol.commit()
        log("copied to the volume in", round(time.time() - t), "s")
        selftest(work, H["GOLD"], log=log)
        shutil.copy(os.path.join(work, "selftest.json"), "/data/serve/selftest.json"); vol.commit()
        print("SERVE_DONE", json.dumps(out), flush=True)

    @app.local_entrypoint()
    def main():
        prep.remote()
