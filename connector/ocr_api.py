"""Remote OCR workers (e.g. a Colab GPU notebook): fetch queued PDFs, upload Kraken's raw page text.

All routes live under /<MAKTABA_OCR_TOKEN>/ocr/ (a separate secret from the MCP link).
  GET  jobs            -> queue with pages total/done and whether the VPS has started the book
  GET  pdf/<id>        -> the book's PDF
  POST upload/<name>   -> raw file body saved to incoming/<name> (new book sources; no overwrite)
  POST result/<id>     -> JSON {"pages": {"12": "<raw kraken text>", ...}} written to ocr/<id>_ocr/raw/p0012.txt
  POST claim/<id>      -> JSON {"worker": "<name>"}: take a book so other helpers skip it. A claim lasts
                          CLAIM_TTL seconds and is refreshed after every chunk; returns {"ok": false, "by": ...}
                          when another helper holds it.
Raw text is Kraken's own output (visual order); ocr_book.sh on the VPS does the clean-up and skips uploaded pages.
"""
import json, os, pathlib, re, subprocess, time
from starlette.responses import FileResponse, JSONResponse

ROOT = pathlib.Path(os.environ.get("MAKTABA_DIR", ".")).resolve()
OCR = ROOT / "ocr"
ID = re.compile(r"^[a-z0-9-]{1,40}$")
_pages = {}
CLAIM_TTL = 900  # a helper that stops uploading for 15 minutes loses its book


def _queue():
    try:
        return json.loads((ROOT / "ocr_queue.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def _pdf(q):
    p = OCR / f"{q['id']}.pdf"
    return p if p.exists() else (ROOT / "cand" / q["cand"] if q.get("cand") else None)


def _claim(book):
    try:
        c = json.loads((OCR / f"{book}_ocr" / ".claim").read_text(encoding="utf-8"))
        return {"by": c["by"], "age": int(time.time() - c["at"])}
    except (FileNotFoundError, ValueError, KeyError):
        return None


def _npages(p):
    if p not in _pages:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=20).stdout
        _pages[p] = int(next(l.split()[1] for l in out.splitlines() if l.startswith("Pages:")))
    return _pages[p]


def register(mcp, token):
    base = f"/{token}/ocr"

    @mcp.custom_route(base + "/jobs", methods=["GET"])
    async def jobs(request):
        out = []
        for q in _queue():
            pdf = _pdf(q)
            if not pdf or not pdf.exists():
                continue
            raw = OCR / f"{q['id']}_ocr" / "raw"
            done = sorted(int(f.name[1:5]) for f in raw.glob("p*.txt") if f.stat().st_size > 0) if raw.exists() else []
            total = _npages(pdf)
            out.append({"id": q["id"], "title": q.get("title"), "pages": total, "done": len(done),
                        "todo": [p for p in range(1, total + 1) if p not in set(done)],
                        "vps_started": (OCR / f"{q['id']}_ocr" / ".vps").exists(), "claim": _claim(q["id"])})
        return JSONResponse(out)

    @mcp.custom_route(base + "/pdf/{book}", methods=["GET"])
    async def pdf(request):
        book = request.path_params["book"]
        q = next((q for q in _queue() if q["id"] == book), None)
        p = _pdf(q) if q and ID.match(book) else None
        if not p or not p.exists():
            return JSONResponse({"error": "unknown book"}, status_code=404)
        return FileResponse(p, media_type="application/pdf", filename=f"{book}.pdf")

    @mcp.custom_route(base + "/{name}", methods=["GET"])
    async def colab_file(request):
        name = request.path_params["name"]
        if name not in ("run.sh", "worker.py", "laptop.sh"):
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(ROOT / "colab" / name, media_type="text/plain")

    @mcp.custom_route(base + "/result/{book}", methods=["POST"])
    async def result(request):
        book = request.path_params["book"]
        if not ID.match(book) or not any(q["id"] == book for q in _queue()):
            return JSONResponse({"error": "unknown book"}, status_code=404)
        body = await request.json()
        raw = OCR / f"{book}_ocr" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        n = 0
        for page, text in body.get("pages", {}).items():
            if str(page).isdigit() and isinstance(text, str) and len(text) < 200_000:
                f = raw / f"p{int(page):04d}.txt"
                if not (f.exists() and f.stat().st_size > 0):   # never overwrite pages the VPS already did
                    f.write_text(text if text.strip() else "\n", encoding="utf-8")
                    n += 1
        return JSONResponse({"saved": n})

    @mcp.custom_route(base + "/claim/{book}", methods=["POST"])
    async def claim(request):
        book = request.path_params["book"]
        if not ID.match(book) or not any(q["id"] == book for q in _queue()):
            return JSONResponse({"error": "unknown book"}, status_code=404)
        worker = str((await request.json()).get("worker", ""))[:80] or "unnamed"
        held = _claim(book)
        if held and held["by"] != worker and held["age"] < CLAIM_TTL:
            return JSONResponse({"ok": False, "by": held["by"], "age": held["age"]})
        d = OCR / f"{book}_ocr"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".claim").write_text(json.dumps({"by": worker, "at": time.time()}), encoding="utf-8")
        return JSONResponse({"ok": True})

    UPNAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

    @mcp.custom_route(base + "/upload/{name}", methods=["POST"])
    async def upload(request):
        """Add a source file for a new book: raw body saved to incoming/<name>; never overwrites."""
        name = request.path_params["name"]
        if not UPNAME.match(name) or name.startswith("."):
            return JSONResponse({"error": "bad name"}, status_code=400)
        body = await request.body()
        if len(body) > 80_000_000:
            return JSONResponse({"error": "too large"}, status_code=413)
        inc = ROOT / "incoming"
        inc.mkdir(exist_ok=True)
        f = inc / name
        if f.exists():
            return JSONResponse({"error": "exists", "bytes": f.stat().st_size}, status_code=409)
        f.write_bytes(body)
        return JSONResponse({"saved": name, "bytes": len(body)})
