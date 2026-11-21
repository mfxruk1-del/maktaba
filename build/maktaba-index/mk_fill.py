# -*- coding: utf-8 -*-
"""Vectors for the passages of data_maktaba that have none yet (data_maktaba/vec_missing.json). Running step 1 spends money on Modal.
Same model and settings as every other build (Arabic-Triplet-Matryoshka-V2 from the Modal volume "shamela-sem", float16, 512 tokens, the first
256 numbers at length 1, one byte each). Only the missing rows are embedded: at 540 passages a second, 581,014 passages are about 0.3 GPU-hours.
   1.  KT_GPUS=2 ~/modal-venv/bin/modal run ~/semsearch/mk/mk_fill.py        (KT_LIMIT=1 = one shard only, as a trial; a finished shard is skipped)
   2.  ~/semsearch/venv/bin/python ~/semsearch/mk/mk_fill.py assemble         writes the vectors into vec256.i8 (a copy of the file is kept), clears the "no_vectors" marks
   3.  restart the search service.
Text reaches the GPU as the argument of each call (8,192 passages, about 2.4 MB compressed); nothing is uploaded beforehand. Paths: SEM_HOME."""
import os, sys, json, time, zlib
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "fill_out")
DATA = os.path.join(os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch")), "data_maktaba")
MODEL_DIR = "models--Omartificial-Intelligence-Space--Arabic-Triplet-Matryoshka-V2"; BLOCK = 256; PER = 8192; DIM = 256; GPUS = int(os.environ.get("KT_GPUS", "1"))


def plan():
    """The missing rows, cut into shards. Written once to fill_out/PLAN.json so that step 2 writes exactly what step 1 embedded."""
    p = os.path.join(OUT, "PLAN.json"); n = int(np.load(os.path.join(DATA, "meta.npy"), mmap_mode="r").shape[0]); mark = {"passages": n, "texts_bin_bytes": os.path.getsize(os.path.join(DATA, "texts.bin"))}
    if os.path.exists(p):
        P = json.load(open(p))
        if P["mark"] != mark: sys.exit("fill_out belongs to another index (the index was rebuilt). Delete %s and start again." % OUT)
        return P
    miss = json.load(open(os.path.join(DATA, "vec_missing.json"), encoding="utf-8")); rng = sorted([m["from"], m["to"]] for m in miss); shards = []; cur = []; size = 0
    for a, b in rng:
        while a < b:
            take = min(b - a, PER - size); cur.append([a, a + take]); size += take; a += take
            if size == PER: shards.append(cur); cur = []; size = 0
    if cur: shards.append(cur)
    P = {"mark": mark, "shards": shards}; os.makedirs(OUT, exist_ok=True); json.dump(P, open(p, "w")); return P


def texts_of(ranges):
    off = np.load(os.path.join(DATA, "text_offsets.npy")); out = []; cache = {}
    with open(os.path.join(DATA, "texts.bin"), "rb") as f:
        for a, b in ranges:
            for i in range(a, b):
                k = i // BLOCK
                if k not in cache:
                    cache.clear(); f.seek(int(off[k])); cache[k] = zlib.decompress(f.read(int(off[k + 1] - off[k]))).decode("utf-8").split("\n")
                out.append(cache[k][i % BLOCK])
    return out


def assemble():
    import shutil
    P = plan(); missing = [k for k in range(len(P["shards"])) if not os.path.exists(os.path.join(OUT, "f%05d.i8" % k))]
    if missing: sys.exit("not assembled: %d of %d shards are not embedded yet" % (len(missing), len(P["shards"])))
    vp = os.path.join(DATA, "vec256.i8"); shutil.copy2(vp, vp + ".before-fill"); X = np.memmap(vp, dtype=np.int8, mode="r+", shape=(P["mark"]["passages"], DIM)); n = 0
    for k, rs in enumerate(P["shards"]):
        V = np.frombuffer(open(os.path.join(OUT, "f%05d.i8" % k), "rb").read(), dtype=np.int8).reshape(-1, DIM); p = 0
        for a, b in rs: X[a:b] = V[p:p + b - a]; p += b - a
        assert p == len(V), (k, p, len(V)); n += p
    X.flush(); del X
    bp = os.path.join(DATA, "books.json"); bk = json.load(open(bp, encoding="utf-8")); m = 0
    for b in bk:
        if b.pop("no_vectors", None): m += 1
    json.dump(bk, open(bp + ".tmp", "w", encoding="utf-8"), ensure_ascii=False); os.replace(bp + ".tmp", bp); json.dump([], open(os.path.join(DATA, "vec_missing.json"), "w"))
    print("FILLED %d passages of %d books. A copy of the file of before: vec256.i8.before-fill. Restart the search service." % (n, m))


if len(sys.argv) > 1 and sys.argv[1] == "assemble" and __name__ == "__main__":
    assemble(); sys.exit(0)

import modal
app = modal.App("maktaba-fill")
vol = modal.Volume.from_name("shamela-sem").read_only()
image = (modal.Image.debian_slim(python_version="3.11").pip_install("torch", "transformers", "sentence-transformers", "numpy").env({"HF_HOME": "/data/hf"}))


@app.cls(image=image, volumes={"/data": vol}, gpu="A10G", cpu=4, memory=10000, timeout=1800, max_containers=GPUS, scaledown_window=20)
class Embedder:
    @modal.enter()
    def load(self):
        import shutil, torch
        os.environ["HF_HUB_OFFLINE"] = "1"; os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        root = "/data/hf/hub/" + MODEL_DIR + "/snapshots"; snap = os.path.join(root, sorted(os.listdir(root))[0])
        shutil.copytree(snap, "/root/model", symlinks=False)
        self.model = SentenceTransformer("/root/model", device="cuda", model_kwargs={"torch_dtype": torch.float16}); self.model.max_seq_length = 512

    @modal.method()
    def embed(self, job):
        import numpy as np
        k, z = job; t0 = time.time(); texts = zlib.decompress(z).decode("utf-8").split("\n")
        E = self.model.encode(texts, batch_size=192, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float16)
        X = E.astype(np.float32)[:, :256]; n = np.linalg.norm(X, axis=1, keepdims=True); n[n == 0] = 1
        return {"k": k, "n": len(texts), "i8": np.clip(np.rint(X / n * 127), -127, 127).astype(np.int8).tobytes(), "s": round(time.time() - t0, 1)}


@app.local_entrypoint()
def main():
    P = plan(); todo = [k for k in range(len(P["shards"])) if not os.path.exists(os.path.join(OUT, "f%05d.i8" % k))]
    if int(os.environ.get("KT_LIMIT", "0")) > 0: todo = todo[:int(os.environ["KT_LIMIT"])]
    total = sum(b - a for k in todo for a, b in P["shards"][k]); print("shards to embed: %d of %d | passages %d | GPUs at once: %d | about %.2f GPU-hours" % (len(todo), len(P["shards"]), total, GPUS, total / 540 / 3600), flush=True)
    t0 = time.time(); done = 0; step = max(2, 2 * GPUS)
    for i in range(0, len(todo), step):
        jobs = []
        for k in todo[i:i + step]:
            tx = texts_of(P["shards"][k]); assert all("\n" not in t for t in tx); jobs.append((k, zlib.compress("\n".join(tx).encode("utf-8"), 6)))
        for r in Embedder().embed.map(jobs, order_outputs=False):
            want = sum(b - a for a, b in P["shards"][r["k"]]); assert r["n"] == want and len(r["i8"]) == want * DIM, (r["k"], r["n"], want)
            p = os.path.join(OUT, "f%05d.i8" % r["k"])
            with open(p + ".tmp", "wb") as f: f.write(r["i8"])
            os.rename(p + ".tmp", p); done += 1; print("shard %d: %d passages in %s s | %d of %d done" % (r["k"], r["n"], r["s"], done, len(todo)), flush=True)
    print("FILL_EMBED_DONE shards %d wall %.0f s. Next: mk_fill.py assemble" % (done, time.time() - t0), flush=True)
