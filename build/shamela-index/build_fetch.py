# -*- coding: utf-8 -*-
# Step A of the full build: copy the Shamela full-text dataset to the Modal volume and measure it.
# No GPU. Output: shamela-sem:/src/... and /manifest.json (per book: ids, pages, characters, estimated passages)
import modal, json, os, re, time

app = modal.App("shamela-fetch")
vol = modal.Volume.from_name("shamela-sem", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.11").pip_install("huggingface_hub", "hf_transfer")
         .env({"HF_HOME": "/data/hf", "HF_HUB_ENABLE_HF_TRANSFER": "1"}))
TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
TAG = re.compile(r"<[^>]+>")

@app.function(image=image, volumes={"/data": vol}, cpu=8, memory=16000, timeout=4 * 3600)
def fetch():
    from huggingface_hub import snapshot_download
    t0 = time.time()
    for attempt in range(6):
        try:
            snapshot_download("AuthenticIlm/Shamela4_Full_DB", repo_type="dataset", local_dir="/data/src",
                              allow_patterns=["*/*/pages.jsonl", "*/*/book_metadata.json"], max_workers=8)
            break
        except Exception as e:
            print("download attempt", attempt, "failed:", repr(e)[:300], flush=True); vol.commit(); time.sleep(60 * (attempt + 1))
    vol.commit(); print("download finished in", round(time.time() - t0), "s", flush=True)
    books = []; tot_chars = 0; tot_pages = 0; tot_bytes = 0
    for cat in sorted(os.listdir("/data/src")):
        cdir = os.path.join("/data/src", cat)
        if not os.path.isdir(cdir) or cat.startswith((".", "_")): continue
        for b in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, b, "pages.jsonl")
            if not os.path.exists(p): continue
            try: md = json.load(open(os.path.join(cdir, b, "book_metadata.json"), encoding="utf-8"))
            except Exception: md = {}
            chars = fchars = pages = 0
            for line in open(p, encoding="utf-8"):
                try: d = json.loads(line)
                except Exception: continue
                pages += 1
                chars += len(re.sub(r"\s+", " ", TASHKEEL.sub("", TAG.sub(" ", d.get("body") or ""))))
                fchars += len(TASHKEEL.sub("", TAG.sub(" ", d.get("footnotes") or "")))
            sz = os.path.getsize(p)
            books.append({"path": cat + "/" + b, "book_id": md.get("book_id"), "shamela_id": md.get("shamela_id"), "title": md.get("title_ar"),
                          "cat": md.get("category_id"), "author": md.get("main_author_name_ar"), "death": md.get("main_author_death_hijri"),
                          "pages": pages, "bytes": sz, "chars": chars, "foot_chars": fchars})
            tot_chars += chars; tot_pages += pages; tot_bytes += sz
        print(cat, "done; books so far", len(books), flush=True)
    out = {"n_books": len(books), "pages": tot_pages, "bytes": tot_bytes, "chars": tot_chars,
           "foot_chars": sum(b["foot_chars"] for b in books), "est_chunks_900": int(tot_chars / 750), "books": books}
    json.dump(out, open("/data/manifest.json", "w"), ensure_ascii=False); vol.commit()
    print("MANIFEST", json.dumps({k: v for k, v in out.items() if k != "books"}), flush=True)

@app.local_entrypoint()
def main():
    fetch.remote()
