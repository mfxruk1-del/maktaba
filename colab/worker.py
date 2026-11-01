# Maktaba OCR worker: takes queued books from the VPS, OCRs them with Kraken (GPU if available), uploads raw text.
import glob, json, os, shutil, subprocess, sys, tempfile, time, urllib.request

SERVER = os.environ.get("MAKTABA_SERVER", "https://maktaba.farabsmp.fun")
TOKEN = os.environ["MAKTABA_OCR_TOKEN"]
DEVICE = os.environ.get("OCR_DEVICE", "cuda:0")
CHUNK = int(os.environ.get("OCR_CHUNK", "20"))
PAR = int(os.environ.get("OCR_PAR", str(os.cpu_count() or 2)))   # Kraken processes at once (segmentation is CPU-bound)
MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "0"))       # 0 = no limit (for testing)
KRAKEN = shutil.which("kraken") or os.path.join(os.path.dirname(sys.executable), "kraken")
MODEL = glob.glob(os.path.expanduser("~/.local/share/htrmopo/*/arabic_best.mlmodel"))[0]
BASE = f"{SERVER}/{TOKEN}/ocr"


def _retry(fn):
    """The VPS restarts its web service when it re-indexes the library; ride out short outages."""
    for i in range(8):
        try:
            return fn()
        except Exception as e:
            if i == 7:
                raise
            print("server unreachable, retrying:", e, flush=True); time.sleep(15 * (i + 1))


def get(path):
    def f():
        with urllib.request.urlopen(f"{BASE}/{path}", timeout=120) as r:
            return json.load(r)
    return _retry(f)


def post(path, data):
    req = urllib.request.Request(f"{BASE}/{path}", data=json.dumps(data).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    def f():
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    return _retry(f)


def pick():
    """Work from the END of the queue so the VPS (which works from the front) and this worker don't collide.
    OCR_BOOK=<id> forces one book (use when the VPS job for it has been stopped)."""
    forced = os.environ.get("OCR_BOOK")
    for j in reversed(get("jobs")):
        if forced:
            if j["id"] == forced and j["todo"]:
                return j
            continue
        if j["todo"] and not j["vps_started"]:
            return j
    return None


done_total, t0 = 0, time.time()
while True:
    job = pick()
    if not job:
        print("Nothing left to do: every queued book is finished or already being done by the VPS.")
        break
    book, work = job["id"], tempfile.mkdtemp()
    print(f"\n=== {book}: {len(job['todo'])} of {job['pages']} pages to do", flush=True)
    pdf = os.path.join(work, "book.pdf")
    urllib.request.urlretrieve(f"{BASE}/pdf/{book}", pdf)
    reverse = os.environ.get("OCR_ORDER") == "reverse"   # two workers on one book: one from each end
    while True:
        # refresh the list of missing pages before every chunk, so workers sharing a book don't redo pages
        todo = next((j["todo"] for j in get("jobs") if j["id"] == book), [])
        if not todo:
            break
        chunk = todo[-CHUNK:][::-1] if reverse else todo[:CHUNK]
        args = []
        for p in chunk:
            img = os.path.join(work, f"p{p:04d}")
            subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "300", "-gray", "-png", "-singlefile", pdf, img],
                           check=True)
            args += ["-i", img + ".png", img + ".txt"]
        t1 = time.time()
        groups = [args[i * 3:(i + 1) * 3] for i in range(len(chunk))]
        procs = []
        for k in range(PAR):
            mine = [a for g in groups[k::PAR] for a in g]
            if mine:
                procs.append(subprocess.Popen([KRAKEN, "-d", DEVICE, *mine, "segment", "-bl", "ocr", "-m", MODEL],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True))
        errs = [pr.communicate()[1] for pr in procs]
        print(f"  kraken {len(chunk)} pages in {time.time() - t1:.0f}s ({len(procs)} processes)", flush=True)
        class r: stderr = "\n".join(e[-700:] for e in errs)
        pages = {}
        for p in chunk:
            f = os.path.join(work, f"p{p:04d}.txt")
            if os.path.exists(f):
                pages[str(p)] = open(f, encoding="utf-8").read()
            for ext in (".png", ".txt"):
                if os.path.exists(os.path.join(work, f"p{p:04d}{ext}")):
                    os.remove(os.path.join(work, f"p{p:04d}{ext}"))
        if not pages:
            print("Kraken produced nothing for this chunk. Last output:\n", r.stderr[-1500:])
            raise SystemExit(1)
        saved = post(f"result/{book}", {"pages": pages})["saved"]
        done_total += len(pages)
        rate = done_total / max(time.time() - t0, 1) * 60
        print(f"  pages {chunk[0]}-{chunk[-1]}: uploaded {saved} · {rate:.1f} pages/min overall", flush=True)
        if MAX_PAGES and done_total >= MAX_PAGES:
            raise SystemExit(0)
        # stop this book if the VPS has started it meanwhile
        if not os.environ.get("OCR_BOOK") and any(j["id"] == book and j["vps_started"] for j in get("jobs")):
            print("  the VPS has started this book; moving on")
            break
    shutil.rmtree(work, ignore_errors=True)
