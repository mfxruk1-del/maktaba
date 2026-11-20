# Step B of the full build: embed every Shamela book (main text + editors' footnotes) on Modal GPUs.
# Reads  shamela-sem:/src/<category>/<book>/pages.jsonl  and  /manifest.json  (made by build_fetch.py)
# Writes shamela-sem:/emb/sNNNN.npy (float16 vectors), sNNNN.meta.npy (int64 rows), sNNNN.txt.gz (one passage per line)
# meta columns: book_id, shamela_id, page_id, shamela_page_id, part, page_num, kind (0 main text, 1 footnote), passage_no
# Safe to re-run: finished shards are skipped.  Usage:  modal run --detach build_embed.py --limit 2  (last 2 shards)  |  --limit -2  (first 2)  |  no --limit (all)
import gzip, json, os, re, time

MODEL = "Omartificial-Intelligence-Space/Arabic-Triplet-Matryoshka-V2"
SHARD_CHARS = 45_000_000        # cleaned characters per shard (about 60,000 passages)
BUDGET_GPU_HOURS = 7.5          # hard stop: the driver aborts the run if total GPU time passes this
TASHKEEL = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
TAG = re.compile(r"<[^>]+>")


def clean(t):
    t = TAG.sub(" ", t or "")
    t = TASHKEEL.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def chunk(text, size=900, overlap=150):
    # identical to the tested version in semtest.py
    words = text.split(" "); out = []; cur = []; n = 0
    for w in words:
        cur.append(w); n += len(w) + 1
        if n >= size:
            out.append(" ".join(cur))
            keep = []; k = 0
            for x in reversed(cur):
                k += len(x) + 1; keep.append(x)
                if k >= overlap: break
            cur = list(reversed(keep)); n = sum(len(x) + 1 for x in cur)
    if cur and (not out or n > overlap + 40): out.append(" ".join(cur))
    return out


def to_int(v, default=-1):
    try: return int(v)
    except Exception: return default


def parse_lines(args):
    """Turn raw page lines of one book into (meta rows, passages): main text first on each page, then its footnotes."""
    book_id, shamela_id, lines = args
    meta = []; texts = []
    for line in lines:
        try: d = json.loads(line)
        except Exception: continue
        base = [to_int(book_id), to_int(shamela_id), to_int(d.get("page_id")), to_int(d.get("shamela_page_id")),
                to_int(d.get("part")), to_int(d.get("page_num"))]
        for kind, field in ((0, "body"), (1, "footnotes")):
            raw = d.get(field)
            if not raw or raw == "None": continue
            text = clean(raw)
            if len(text) < 40: continue
            for no, c in enumerate(chunk(text)):
                meta.append(base + [kind, no]); texts.append(c)
    return meta, texts


def book_tasks(src_root, path, book_id, shamela_id, batch=3000):
    with open(os.path.join(src_root, path, "pages.jsonl"), encoding="utf-8") as f:
        lines = f.readlines()
    return [(book_id, shamela_id, lines[i:i + batch]) for i in range(0, len(lines), batch)]


def encode_shard(model, src_root, out_dir, sid, books, batch_size=128, pool=None):
    """books: list of [path, book_id, shamela_id]. Returns a small summary dict."""
    import numpy as np
    stem = os.path.join(out_dir, "s%04d" % sid)
    if os.path.exists(stem + ".npy") and os.path.exists(stem + ".meta.npy") and os.path.exists(stem + ".txt.gz"):
        return {"sid": sid, "skipped": True}
    t0 = time.time(); meta = []; texts = []; missing = 0
    from concurrent.futures import ThreadPoolExecutor
    def load(b):                                              # file reads are slow on a network volume: do them in threads
        if not os.path.exists(os.path.join(src_root, b[0], "pages.jsonl")): return None
        return book_tasks(src_root, b[0], b[1], b[2])
    tasks = []
    with ThreadPoolExecutor(16) as tp:
        for got in tp.map(load, books):
            if got is None: missing += 1
            else: tasks += got
    t_read = time.time()
    for m, t in (pool.map(parse_lines, tasks, chunksize=1) if pool else map(parse_lines, tasks)):
        meta += m; texts += t
    t1 = time.time()
    if texts:
        E = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        E = E.astype(np.float16)
    else:
        E = np.zeros((0, 768), np.float16)
    t2 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    with gzip.open(stem + ".txt.gz.tmp", "wt", encoding="utf-8", compresslevel=4) as g:
        for c in texts: g.write(c.replace("\n", " ") + "\n")
    np.save(stem + ".meta.tmp.npy", np.array(meta, dtype=np.int64).reshape(-1, 8))
    np.save(stem + ".tmp.npy", E)
    os.replace(stem + ".txt.gz.tmp", stem + ".txt.gz")
    os.replace(stem + ".meta.tmp.npy", stem + ".meta.npy")
    os.replace(stem + ".tmp.npy", stem + ".npy")          # vectors last: their presence marks the shard as done
    return {"sid": sid, "skipped": False, "books": len(books), "missing": missing, "passages": len(texts),
            "read_s": round(t_read - t0, 1), "parse_s": round(t1 - t_read, 1), "gpu_s": round(t2 - t1, 1), "total_s": round(time.time() - t0, 1)}


def plan_shards(books):
    """Greedy packing by cleaned characters, biggest books first. books: manifest entries."""
    items = sorted(books, key=lambda b: -(b["chars"] + b["foot_chars"]))
    shards = []; cur = []; n = 0
    for b in items:
        size = b["chars"] + b["foot_chars"]
        if size == 0: continue
        if cur and n + size > SHARD_CHARS: shards.append(cur); cur = []; n = 0
        cur.append([b["path"], b["book_id"], b["shamela_id"]]); n += size
    if cur: shards.append(cur)
    return shards

# --- modal ---
import modal

app = modal.App("shamela-embed")
vol = modal.Volume.from_name("shamela-sem")
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install("torch", "transformers", "sentence-transformers", "numpy")
         .env({"HF_HOME": "/data/hf"}))


@app.cls(image=image, volumes={"/data": vol}, gpu="A10G", cpu=4, memory=10000, timeout=2400, max_containers=6, retries=1)
class Embedder:
    @modal.enter()
    def load(self):
        from concurrent.futures import ProcessPoolExecutor
        self.pool = ProcessPoolExecutor(4)                    # started before CUDA so the workers are clean forks
        list(self.pool.map(to_int, range(8)))
        import torch
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(MODEL, device="cuda", model_kwargs={"torch_dtype": torch.float16})
        self.model.max_seq_length = 512

    @modal.method()
    def shard(self, sid, books):
        r = encode_shard(self.model, "/data/src", "/data/emb", sid, books, batch_size=192, pool=self.pool)
        vol.commit()
        return r


@app.function(image=image, volumes={"/data": vol}, cpu=2, memory=4000, timeout=8 * 3600)
def driver(limit: int = 0):
    man = json.load(open("/data/manifest.json", encoding="utf-8"))
    shards = plan_shards(man["books"])
    jobs = list(enumerate(shards))
    print("planned", len(jobs), "shards for", man["n_books"], "books", flush=True)
    if limit > 0: jobs = jobs[-limit:]      # the last shards hold the smallest books: a cheap test
    if limit < 0: jobs = jobs[:-limit]      # the first shards hold the largest books
    gpu_s = 0.0; passages = 0; done = 0; t0 = time.time()
    for r in Embedder().shard.starmap(jobs, order_outputs=False, return_exceptions=True):
        done += 1
        if isinstance(r, Exception):
            print("SHARD FAILED", repr(r)[:300], flush=True); continue
        if not r.get("skipped"):
            gpu_s += r["total_s"]; passages += r["passages"]
        print(done, "/", len(jobs), json.dumps(r), "| passages so far", passages, "| GPU hours", round(gpu_s / 3600, 2), flush=True)
        if gpu_s / 3600 > BUDGET_GPU_HOURS:
            raise RuntimeError("GPU budget passed; stopping. Re-run to resume after checking.")
    try: vol.reload()
    except Exception as e: print('reload skipped:', repr(e)[:120], flush=True)
    have = sorted(f for f in os.listdir("/data/emb") if f.endswith(".npy") and ".meta" not in f and ".tmp" not in f)
    summary = {"shards_planned": len(shards), "shards_run": len(jobs), "shard_files": len(have), "new_passages": passages,
               "gpu_hours": round(gpu_s / 3600, 2), "wall_minutes": round((time.time() - t0) / 60, 1)}
    json.dump({"summary": summary, "shards": shards}, open("/data/emb/plan.json", "w"), ensure_ascii=False)
    vol.commit()
    print("EMBED_SUMMARY", json.dumps(summary), flush=True)


@app.local_entrypoint()
def main(limit: int = 0):
    driver.remote(limit)
