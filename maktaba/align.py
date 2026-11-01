"""Find which printed page of a typed edition each sampled scan page shows (to attach scans to typed text).

Usage: python align.py typed.jsonl scan.pdf pdf_page [pdf_page ...]
OCRs the sampled pages with Kraken and matches them to the typed pages by word overlap.
Prints, per sampled page: best printed page, overlap score, and pdf - printed.
"""
import json, re, subprocess, sys, pathlib, tempfile, glob, os
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from arabic import norm

typed, pdf, pages = sys.argv[1], sys.argv[2], [int(p) for p in sys.argv[3:]]
W = re.compile(r"[ء-ي]{3,}")
recs = [json.loads(l) for l in open(typed, encoding="utf-8") if l.strip()]
sets = [set(W.findall(norm(r["text"]))) for r in recs]
model = glob.glob(os.path.expanduser("~/.local/share/htrmopo/*/arabic_best.mlmodel"))[0]
tmp = pathlib.Path(tempfile.mkdtemp())
args = []
for p in pages:
    subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "250", "-gray", "-png", "-singlefile", pdf,
                    str(tmp / f"p{p}")], check=True)
    args += ["-i", str(tmp / f"p{p}.png"), str(tmp / f"p{p}.txt")]
subprocess.run([os.path.expanduser("~/kraken/bin/kraken"), *args, "segment", "-bl", "ocr", "-m", model],
               capture_output=True)
for p in pages:
    f = tmp / f"p{p}.txt"
    if not f.exists():
        print(p, "OCR failed"); continue
    text = "\n".join(l[::-1] for l in f.read_text(encoding="utf-8").splitlines())   # visual -> logical order
    s = set(W.findall(norm(text)))
    if not s:
        print(p, "empty page"); continue
    score, i = max((len(s & t) / (len(s | t) or 1), i) for i, t in enumerate(sets))
    pr = recs[i].get("printed")
    num = str(pr).rpartition("/")[2] if pr else ""
    print(f"pdf {p}: matches typed page {recs[i]['page']}, printed {pr} (score {score:.2f})" + (f"  offset {p - int(num)}" if num.isdigit() else ""))
