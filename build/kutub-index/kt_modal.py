# -*- coding: utf-8 -*-
"""READY BUT NEVER RUN (written 20 Nov 2026). Running it spends money on Modal: every passage of the Kutub index is embedded, which for
the index built on 20 Nov 2026 (2,296,918 passages) is about 1.2 GPU-hours on one A10G at the rate measured for Maktaba (540 a second).
Vectors for data_kutub, made the way mk/mk_modal.py made Maktaba's: model Arabic-Triplet-Matryoshka-V2 from the Modal volume
"shamela-sem", float16, 512 tokens, the first 256 numbers of each vector at length 1, one byte each.

HOW THE TEXT REACHES THE GPU: nothing is uploaded beforehand. This program reads data_kutub/texts.bin on this machine and sends, as the
ARGUMENT of each remote call, one shard = 32 of that file's zlib blocks = 8,192 passages (about 2.5 MB, still compressed); the GPU
container unpacks, embeds and returns 8,192 x 256 bytes. A few shards are in flight at a time; a finished shard (out/kNNNNN.i8) is
skipped, so a run that was cut off is simply started again.
WHAT WOULD MAKE IT FAIL: the volume "shamela-sem" no longer holding the model; a Modal limit or version change (the 2.5 MB arguments
and this `.map` call were never tried); the index being rebuilt between the embedding and `assemble` (refused: out/INDEX.json records
which index the shards belong to, delete out/ to start over).

   1.  ~/modal-venv/bin/modal run ~/semsearch/kutub/kt_modal.py            (KT_GPUS=2 for two GPUs at once: same GPU-hours, half the wait; KT_LIMIT=2 embeds only two shards, as a trial)
   2.  ~/semsearch/venv/bin/python ~/semsearch/kutub/kt_modal.py assemble  -> data_kutub/vec256.i8 (N x 256 int8)
   3.  restart the search service: an index WITH vec256.i8 gets meaning-search by itself (semcore.Searcher), nothing else to change.
Paths: SEM_HOME (default ~/semsearch) in the environment."""
import os, sys, json, time, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
DATA = os.path.join(os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch")), "data_kutub")
MODEL_DIR = "models--Omartificial-Intelligence-Space--Arabic-Triplet-Matryoshka-V2"
BLOCK = 256; PER_SHARD = 32; DIM = 256; GPUS = int(os.environ.get("KT_GPUS", "1"))


def index_mark():
    """Which index this is: its passage count and the size of its texts.bin."""
    import numpy as np
    return {"passages": int(np.load(os.path.join(DATA, "meta.npy"), mmap_mode="r").shape[0]), "texts_bin_bytes": os.path.getsize(os.path.join(DATA, "texts.bin"))}


def same_index():
    """True when the shards in out/ were cut from the index that is there now (the mark is written with the first shard)."""
    p = os.path.join(OUT, "INDEX.json")
    if not os.path.exists(p):
        if any(f.endswith(".i8") for f in os.listdir(OUT)): return False
        json.dump(index_mark(), open(p, "w")); return True
    return json.load(open(p)) == index_mark()


def shard_count():
    import numpy as np
    return -(-(len(np.load(os.path.join(DATA, "text_offsets.npy"))) - 1) // PER_SHARD)


def shard_blocks(k):
    """The compressed blocks of shard k, straight from texts.bin."""
    import numpy as np
    off = np.load(os.path.join(DATA, "text_offsets.npy")); a = k * PER_SHARD; b = min(a + PER_SHARD, len(off) - 1); out = []
    with open(os.path.join(DATA, "texts.bin"), "rb") as f:
        for i in range(a, b):
            f.seek(int(off[i])); out.append(f.read(int(off[i + 1] - off[i])))
    return out


def assemble():
    n = index_mark()["passages"]; ks = shard_count()
    if not os.path.isdir(OUT) or not same_index(): sys.exit("not assembled: the shards in out/ do not belong to the index that is in data_kutub now")
    missing = [k for k in range(ks) if not os.path.exists(os.path.join(OUT, "k%05d.i8" % k))]
    if missing: sys.exit("not assembled: %d of %d shards are not embedded yet (first: %d)" % (len(missing), ks, missing[0]))
    tmp = os.path.join(DATA, "vec256.i8.tmp"); done = 0
    with open(tmp, "wb") as f:
        for k in range(ks):
            b = open(os.path.join(OUT, "k%05d.i8" % k), "rb").read(); assert len(b) % DIM == 0; f.write(b); done += len(b) // DIM
    if done != n: os.remove(tmp); sys.exit("not assembled: %d vectors for %d passages" % (done, n))
    os.rename(tmp, os.path.join(DATA, "vec256.i8")); print("ASSEMBLED vec256.i8: %d vectors x %d. Restart the search service to use them." % (n, DIM))


if len(sys.argv) > 1 and sys.argv[1] == "assemble" and __name__ == "__main__":
    assemble(); sys.exit(0)

import modal
app = modal.App("kutub-embed")
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
        k, blocks = job; t0 = time.time(); texts = []
        for z in blocks: texts += zlib.decompress(z).decode("utf-8").split("\n")
        E = self.model.encode(texts, batch_size=192, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float16)
        X = E.astype(np.float32)[:, :256]; n = np.linalg.norm(X, axis=1, keepdims=True); n[n == 0] = 1
        return {"k": k, "n": len(texts), "dim": int(E.shape[1]), "i8": np.clip(np.rint(X / n * 127), -127, 127).astype(np.int8).tobytes(), "s": round(time.time() - t0, 1)}


@app.local_entrypoint()
def main():
    os.makedirs(OUT, exist_ok=True); ks = shard_count(); mark = index_mark()
    if not same_index(): sys.exit("stopped: out/ holds shards of another index (the index was rebuilt since). Delete %s and start again." % OUT)
    todo = [k for k in range(ks) if not os.path.exists(os.path.join(OUT, "k%05d.i8" % k))]
    if int(os.environ.get("KT_LIMIT", "0")) > 0: todo = todo[:int(os.environ["KT_LIMIT"])]      # a trial run: only the first few shards
    print("passages %d | shards to embed: %d of %d (8,192 passages each) | GPUs at once: %d | about %.1f GPU-hours at 540 passages a second"
          % (mark["passages"], len(todo), ks, GPUS, len(todo) * 8192 / 540 / 3600), flush=True); t0 = time.time(); total = 0
    step = max(2, 2 * GPUS); done = 0                            # a few shards in flight at a time: the texts are read from disk as they are sent
    for i in range(0, len(todo), step):
        for r in Embedder().embed.map([(k, shard_blocks(k)) for k in todo[i:i + step]], order_outputs=False):
            assert len(r["i8"]) == r["n"] * DIM
            p = os.path.join(OUT, "k%05d.i8" % r["k"])
            with open(p + ".tmp", "wb") as f: f.write(r["i8"])
            os.rename(p + ".tmp", p); total += r["n"]; done += 1
            print("shard %d: %d passages in %s s | dim %d | %d of %d shards done" % (r["k"], r["n"], r["s"], r["dim"], done, len(todo)), flush=True)
    print("EMBED_DONE passages %d wall %.0f s. Next: python kt_modal.py assemble" % (total, time.time() - t0), flush=True)
