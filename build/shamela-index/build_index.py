# -*- coding: utf-8 -*-
# Step C: build the search indexes from the embedded shards and test them on the WHOLE library.
# Reads  shamela-sem:/emb/sNNNN.{npy,meta.npy,txt.gz}
# Writes shamela-sem:/index/  ivf256.faiss, meta.npy (int32 [N,8]), shard_offsets.json, kw/ (tantivy), eval_full.json
import gzip, glob, json, os, re, time

MODEL = "Omartificial-Intelligence-Space/Arabic-Triplet-Matryoshka-V2"
RERANKER = "BAAI/bge-reranker-v2-m3"
DIM = 256
# (id, dataset book_id, part, page, Arabic question) - pages verified by key phrase in the earlier tests
GOLD = [
 ("radd-nikah", 5775, 3, 27, "حكم من جعل النبي شاهدا على عقد الزواج هل يكفر"),
 ("radd-yahadir", 5775, 4, 259, "وصف الله بأنه موجود ويرى في النداء هل هو كفر"),
 ("radd-alive", 5775, 4, 151, "حياة الأنبياء بعد الموت"),
 ("radd-tashahhud", 5775, 1, 510, "هل المصلي يخاطب النبي حقيقة عند قوله السلام عليك أيها النبي في التشهد"),
 ("radd-twoplaces", 5775, 3, 551, "ولي يوجد في مكانين في وقت واحد"),
 ("radd-tawassul", 5775, 6, 397, "طلب الشفاعة والتوسل بالنبي إلى الله في الدعاء"),
 ("radd-hearing", 5775, 3, 836, "هل الميت يسمع كلام الأحياء"),
 ("radd-talqin", 5775, 2, 191, "تذكير الميت بالشهادة بعد وضعه في القبر"),
 ("rasail-awake", 1442, 2, 301, "هل يمكن أن يرى الصالحون النبي وهم مستيقظون لا في المنام"),
 ("rasail-ghayb", 1442, 2, 316, "هل يعلم الأنبياء الغيب وما حكم من ادعى معرفته بنفسه"),
 ("rasail-badal", 1441, 2, 266, "الأبدال إذا سافر أحدهم ترك في مكانه صورة تشبهه"),
 ("bahr-arwah", 4548, 5, 134, "من قال إن نفوس الأولياء الموتى تحضر مجالسنا وتعرف أحوالنا"),
 ("shifa-house", 3601, 2, 118, "لماذا يسلم الداخل على النبي إذا دخل بيتا ليس فيه أحد"),
 ("madkhal-sees", 4268, 1, 259, "النبي يطلع على أمته ويعرف أحوالهم ونياتهم بعد وفاته"),
 ("hawi-moves", 5835, 2, 319, "النبي حي بجسده وروحه وينتقل في أقطار الأرض والملكوت"),
 ("hawi-two", 5835, 1, 254, "شخص واحد يرى في مكانين في آن واحد"),
 ("mirqat-bodies", 2870, 3, 1183, "أرواح الأولياء تظهر في أجساد كثيرة في أماكن مختلفة"),
 ("ruh-travel", 6100, 10, 99, "هل لروح النبي أن تسير في الأكوان مع أرواح أصحابه"),
]
TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
WORD = re.compile("[ء-ي]+")


def norm(t):
    t = TASHKEEL.sub("", t or "")
    t = re.sub("[إأآٱ]", "ا", t)
    return t.replace("ى", "ي").replace("ة", "ه")


def stem(w):
    for p in ("وال", "بال", "فال", "كال", "لل", "ال"):
        if w.startswith(p) and len(w) - len(p) >= 3: return w[len(p):]
    if w[:1] in "وف" and len(w) >= 5: return w[1:]
    return w


def toks(t):
    # same keyword normalisation as the tested BM25: strip marks, unify letter forms, drop common prefixes
    return [stem(w) for w in WORD.findall(norm(t)) if len(w) > 1]


def shard_files(emb_dir):
    return sorted(f for f in glob.glob(os.path.join(emb_dir, "s[0-9][0-9][0-9][0-9].npy")))


def tok_shard(path):
    with gzip.open(path[:-4] + ".txt.gz", "rt", encoding="utf-8") as g:
        return [" ".join(toks(line)) for line in g.read().split("\n")[:-1]]


def renorm(a):
    import numpy as np
    n = np.linalg.norm(a, axis=1, keepdims=True); n[n == 0] = 1
    return a / n


def first_rank(ids, meta, g, limit=1000):
    for r, i in enumerate(ids[:limit], 1):
        if int(i) < 0: continue
        m = meta[int(i)]
        if m[0] == g[1] and m[4] == g[2] and abs(int(m[5]) - g[3]) <= 1: return r
    return None


def run_build(emb_dir, out_dir, nlist=4096, tok_procs=14, rerank=True, log=print):
    import numpy as np, faiss, tantivy, torch
    from multiprocessing import Pool
    from sentence_transformers import SentenceTransformer
    os.makedirs(out_dir, exist_ok=True)
    files = shard_files(emb_dir); T0 = time.time()
    metas = [np.load(f[:-4] + ".meta.npy") for f in files]
    counts = [len(m) for m in metas]; N = int(sum(counts)); offs = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    meta = np.concatenate(metas).astype(np.int32); del metas
    np.save(os.path.join(out_dir, "meta.npy"), meta)
    json.dump({"files": [os.path.basename(f) for f in files], "offsets": offs.tolist(), "n": N, "dim": DIM, "model": MODEL},
              open(os.path.join(out_dir, "shard_offsets.json"), "w"))
    log("shards", len(files), "passages", N, "footnote passages", int((meta[:, 6] == 1).sum()))
    # queries
    m = SentenceTransformer(MODEL, device="cpu"); m.max_seq_length = 512
    Q = m.encode([g[4] for g in GOLD], normalize_embeddings=True).astype(np.float32); Qd = renorm(Q[:, :DIM].copy())
    del m
    # pass 1: load vectors, keep 256 dims, exact full-size search on the way
    X = np.empty((N, DIM), np.float32); K = 200
    top_s = np.full((len(GOLD), K), -9.0, np.float32); top_i = np.zeros((len(GOLD), K), np.int64)
    for k, f in enumerate(files):
        E = np.load(f).astype(np.float32); o = int(offs[k])
        if len(E) != counts[k]: raise RuntimeError("row mismatch in " + f)
        if len(E) == 0: continue
        S = Q @ E.T
        kk = min(K, S.shape[1]); part = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
        cs = np.concatenate([top_s, np.take_along_axis(S, part, 1)], 1); ci = np.concatenate([top_i, part + o], 1)
        sel = np.argsort(-cs, 1)[:, :K]; top_s = np.take_along_axis(cs, sel, 1); top_i = np.take_along_axis(ci, sel, 1)
        X[o:o + len(E)] = renorm(E[:, :DIM])
        if k % 25 == 0: log("loaded", k + 1, "/", len(files), round(time.time() - T0), "s")
    exact768 = top_i
    # exact search on the short vectors
    flat = np.zeros((len(GOLD), 1000), np.int64); B = 2_000_000
    fs = np.full((len(GOLD), 1000), -9.0, np.float32)
    for a in range(0, N, B):
        S = Qd @ X[a:a + B].T; kk = min(1000, S.shape[1]); part = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
        cs = np.concatenate([fs, np.take_along_axis(S, part, 1)], 1); ci = np.concatenate([flat, part + a], 1)
        sel = np.argsort(-cs, 1)[:, :1000]; fs = np.take_along_axis(cs, sel, 1); flat = np.take_along_axis(ci, sel, 1)
    log("exact searches done", round(time.time() - T0), "s")
    # compressed index for the server
    faiss.omp_set_num_threads(max(1, os.cpu_count() or 1))
    index = faiss.index_factory(DIM, "IVF%d,SQ8" % nlist, faiss.METRIC_INNER_PRODUCT)
    rng = np.random.default_rng(0); ntrain = min(N, max(nlist * 64, 10000))
    index.train(X[np.sort(rng.choice(N, ntrain, replace=False))]); log("index trained", round(time.time() - T0), "s")
    for a in range(0, N, B): index.add(X[a:a + B])
    faiss.write_index(index, os.path.join(out_dir, "ivf%d.faiss" % DIM))
    log("index written", round(os.path.getsize(os.path.join(out_dir, "ivf%d.faiss" % DIM)) / 1e9, 2), "GB", round(time.time() - T0), "s")
    ivf = {}
    for nprobe in (16, 64):
        index.nprobe = min(nprobe, nlist); t = time.time(); _, I = index.search(Qd, 1000)
        ivf[nprobe] = I; log("ivf nprobe", nprobe, "ms per query", round((time.time() - t) * 1000 / len(GOLD), 1))
    del X
    # keyword index
    kw_dir = os.path.join(out_dir, "kw"); os.makedirs(kw_dir, exist_ok=True)
    sb = tantivy.SchemaBuilder(); sb.add_text_field("t", stored=False, tokenizer_name="whitespace")
    sb.add_unsigned_field("id", stored=True, indexed=False, fast=True)
    tix = tantivy.Index(sb.build(), path=kw_dir); w = tix.writer(heap_size=3_000_000_000, num_threads=8); gid = 0
    with Pool(tok_procs) as pool:
        for k, lines in enumerate(pool.imap(tok_shard, files, chunksize=1)):
            if len(lines) != counts[k]: raise RuntimeError("text rows mismatch in " + files[k])
            for t in lines:
                d = tantivy.Document(); d.add_text("t", t); d.add_unsigned("id", gid); w.add_document(d); gid += 1
            if k % 25 == 0: log("keyword index", k + 1, "/", len(files), round(time.time() - T0), "s")
    w.commit(); w.wait_merging_threads(); tix.reload(); s = tix.searcher()
    log("keyword index done, docs", s.num_docs, round(time.time() - T0), "s")
    bm = []
    t = time.time()
    for g in GOLD:
        q = tix.parse_query(" ".join(toks(g[4])), ["t"])
        bm.append([s.doc(a)["id"][0] for _, a in s.search(q, 1000).hits])
    log("keyword ms per query", round((time.time() - t) * 1000 / len(GOLD), 1))
    # fusion and candidates
    def rrf(a, b):
        sc = {}
        for lst in (a, b):
            for r, i in enumerate(lst, 1):
                if int(i) >= 0: sc[int(i)] = sc.get(int(i), 0.0) + 1.0 / (60 + r)
        return sorted(sc, key=lambda i: -sc[i])
    hyb = [rrf(ivf[64][k], bm[k]) for k in range(len(GOLD))]
    res = {"n": N, "ranks": {}}
    need = sorted({i for h in hyb for i in h[:50]})
    texts = {}
    if rerank:
        by_shard = {}
        for i in need:
            k = int(np.searchsorted(offs, i, side="right") - 1); by_shard.setdefault(k, []).append(i - int(offs[k]))
        for k, rows in by_shard.items():
            with gzip.open(files[k][:-4] + ".txt.gz", "rt", encoding="utf-8") as g: lines = g.read().split("\n")
            for r in rows: texts[int(offs[k]) + r] = lines[r]
        from sentence_transformers import CrossEncoder
        torch.set_num_threads(max(1, os.cpu_count() or 1))
        rer = CrossEncoder(RERANKER, device="cpu", max_length=512); t = time.time()
    for k, g in enumerate(GOLD):
        r = {"exact768": first_rank(exact768[k], meta, g), "exact256": first_rank(flat[k], meta, g),
             "ivf16": first_rank(ivf[16][k], meta, g), "ivf64": first_rank(ivf[64][k], meta, g),
             "keyword": first_rank(bm[k], meta, g), "hybrid": first_rank(hyb[k], meta, g, 2000)}
        if rerank:
            cand = hyb[k][:50]; sc = rer.predict([(g[4], texts[i]) for i in cand], batch_size=16)
            order = [cand[j] for j in np.argsort(-np.array(sc))]; r["rerank50"] = first_rank(order, meta, g)
            r["top3"] = [[int(x) for x in meta[i][[0, 1, 4, 5, 6]]] for i in order[:3]]
        res["ranks"][g[0]] = r; log(g[0], json.dumps(r))
    if rerank: res["rerank_s_per_query_cpu"] = round((time.time() - t) / len(GOLD), 1)
    res["overlap_ivf64_vs_exact256_top50"] = round(float(np.mean([len(set(ivf[64][k][:50]) & set(flat[k][:50])) / 50 for k in range(len(GOLD))])), 3)
    res["total_s"] = round(time.time() - T0)
    json.dump(res, open(os.path.join(out_dir, "eval_full.json"), "w"), ensure_ascii=False)
    return res

# --- modal ---
import modal

app = modal.App("shamela-index")
vol = modal.Volume.from_name("shamela-sem")
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install("torch", "transformers", "sentence-transformers", "numpy", "faiss-cpu", "tantivy")
         .env({"HF_HOME": "/data/hf"}))


@app.function(image=image, volumes={"/data": vol}, cpu=16, memory=72000, timeout=4 * 3600)
def build():
    def log(*a): print(*a, flush=True)
    res = run_build("/data/emb", "/data/index", log=log)
    vol.commit()
    summary = {k: v for k, v in res.items() if k != "ranks"}
    print("INDEX_SUMMARY", json.dumps(summary), flush=True)


@app.local_entrypoint()
def main():
    build.remote()
