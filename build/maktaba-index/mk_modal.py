# -*- coding: utf-8 -*-
"""Step 2 of the Maktaba index: embed the passages on one Modal GPU with the model and settings of the Shamela build
(Arabic-Triplet-Matryoshka-V2 from the volume's cache, float16, 512 tokens), and return what the server stores: the first 256 numbers
of each vector, length 1, as one byte each.     ~/modal-venv/bin/modal run mk_modal.py      (a finished shard is skipped)"""
import os, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "Omartificial-Intelligence-Space/Arabic-Triplet-Matryoshka-V2"; MODEL_DIR = "models--Omartificial-Intelligence-Space--Arabic-Triplet-Matryoshka-V2"
import modal
app = modal.App("maktaba-embed")
vol = modal.Volume.from_name("shamela-sem").read_only()
image = (modal.Image.debian_slim(python_version="3.11").pip_install("torch", "transformers", "sentence-transformers", "numpy").env({"HF_HOME": "/data/hf"}))
if os.path.isdir(os.path.join(HERE, "ship")): image = image.add_local_dir(os.path.join(HERE, "ship"), "/mk")


@app.cls(image=image, volumes={"/data": vol}, gpu="A10G", cpu=4, memory=10000, timeout=1200, max_containers=1, scaledown_window=20)
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
    def embed(self, name):
        import numpy as np
        t0 = time.time(); texts = json.load(open("/mk/" + name, encoding="utf-8"))
        E = self.model.encode(texts, batch_size=192, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float16)
        X = E.astype(np.float32)[:, :256]; n = np.linalg.norm(X, axis=1, keepdims=True); n[n == 0] = 1
        return {"name": name, "n": len(texts), "dim": int(E.shape[1]), "i8": np.clip(np.rint(X / n * 127), -127, 127).astype(np.int8).tobytes(), "s": round(time.time() - t0, 1)}


@app.local_entrypoint()
def main():
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    names = sorted(f for f in os.listdir(os.path.join(HERE, "ship")) if f.endswith(".json") and not os.path.exists(os.path.join(HERE, "out", f[:-5] + ".i8")))
    print("shards to embed:", len(names), flush=True); t0 = time.time(); total = 0
    for r in Embedder().embed.map(names, order_outputs=False):
        assert len(r["i8"]) == r["n"] * 256
        with open(os.path.join(HERE, "out", r["name"][:-5] + ".i8.tmp"), "wb") as f: f.write(r["i8"])
        os.rename(os.path.join(HERE, "out", r["name"][:-5] + ".i8.tmp"), os.path.join(HERE, "out", r["name"][:-5] + ".i8")); total += r["n"]
        print(r["name"], r["n"], "passages", r["s"], "s | dim", r["dim"], flush=True)
    print("EMBED_DONE passages %d wall %.0f s" % (total, time.time() - t0), flush=True)
