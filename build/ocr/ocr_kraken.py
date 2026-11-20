"""Kraken OCR on Modal, for Maktaba.

Same recipe as ~/library/ocr_book.sh step 2 (render 300-dpi gray PNG, `kraken segment -bl ocr -m arabic_best.mlmodel`),
but the pages are split into batches that run in parallel containers.
It writes RAW kraken output only (raw/pNNNN.txt, visual order); the clean-up step
(reverse lines, swap brackets, NFC, jsonl) is done afterwards by ~/library/ocr_clean.py, exactly as ocr_book.sh does.

One-time setup (already done by the helper commands):
    modal volume create maktaba-ocr
    modal volume put maktaba-ocr <arabic_best.mlmodel> /model/arabic_best.mlmodel
    modal volume put maktaba-ocr <book.pdf> /pdf/<book>.pdf
Run:
    modal run ocr_kraken.py --pdf <book>.pdf --first 101 --last 120 --batch 10 --out test_<book> [--device cpu]
Fetch:
    modal volume get maktaba-ocr /out/test_<book>/raw <local dir>
"""
import modal

VOL_NAME = "maktaba-ocr"
vol = modal.Volume.from_name(VOL_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("poppler-utils", "libgl1", "libglib2.0-0", "libgomp1")
    .pip_install("kraken==7.1.1")
)
app = modal.App("maktaba-ocr", image=image, volumes={"/vol": vol})

GPU = "T4"


def _work(pdf: str, pages: list, out: str, dpi: int, device: str, model: str):
    import os, subprocess, time, pathlib
    t0 = time.time()
    img = pathlib.Path("/tmp/img"); img.mkdir(exist_ok=True)
    raw = pathlib.Path(f"/vol/out/{out}/raw"); raw.mkdir(parents=True, exist_ok=True)
    pdfp = f"/vol/pdf/{pdf}"
    todo = []
    for p in pages:
        b = f"p{p:04d}"
        if (raw / f"{b}.txt").exists() and (raw / f"{b}.txt").stat().st_size > 0:
            continue
        subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", str(dpi), "-gray", "-png",
                        "-singlefile", pdfp, str(img / b)], check=True)
        todo.append(b)
    t_render = time.time() - t0
    t1 = time.time()
    if todo:
        args = ["kraken", "-d", device]
        for b in todo:
            args += ["-i", str(img / f"{b}.png"), str(raw / f"{b}.txt")]
        args += ["segment", "-bl", "ocr", "-m", model]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-2000:])
            raise RuntimeError("kraken failed")
    t_ocr = time.time() - t1
    vol.commit()
    return {"pages": [pages[0], pages[-1]], "n": len(pages), "done": len(todo),
            "render_s": round(t_render, 1), "ocr_s": round(t_ocr, 1), "total_s": round(time.time() - t0, 1)}


@app.function(gpu=GPU, cpu=4, memory=8192, timeout=3600, retries=1)
def ocr_gpu(pdf, pages, out, dpi=300):
    return _work(pdf, pages, out, dpi, "cuda:0", "/vol/model/arabic_best.mlmodel")


@app.function(cpu=4, memory=8192, timeout=3600, retries=1)
def ocr_cpu(pdf, pages, out, dpi=300):
    return _work(pdf, pages, out, dpi, "cpu", "/vol/model/arabic_best.mlmodel")


@app.local_entrypoint()
def main(pdf: str, first: int, last: int, out: str, batch: int = 10, dpi: int = 300, device: str = "cuda"):
    import time
    fn = ocr_gpu if device == "cuda" else ocr_cpu
    batches = []
    p = first
    while p <= last:
        batches.append(list(range(p, min(p + batch, last + 1))))
        p += batch
    print(f"{len(batches)} batches of <= {batch} pages, device={device}")
    t0 = time.time()
    for r in fn.starmap([(pdf, b, out, dpi) for b in batches]):
        print(r, flush=True)
    print(f"wall time {time.time()-t0:.0f}s")
