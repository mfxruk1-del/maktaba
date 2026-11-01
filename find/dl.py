"""Download chosen archive.org files into ~/library/cand/<dir>/ (skip existing)."""
import json, urllib.request, urllib.parse, re, subprocess, pathlib, sys
JOBS = [  # (dir, item, regex of file names to take)
  ("tatarkhaniyya", "Fatawatatarkhania", r"^Fattatar\d\d\.pdf$"),
  ("dhakhira",      "15_20200929_202009", r"^\d\d\.pdf$|^\d\d_text\.pdf$"),
  ("muhit-radawi",  "20250905_20250905_1028", r".*\.pdf$"),
]
base = pathlib.Path.home() / "library" / "cand"
for d, item, rx in JOBS:
    out = base / d; out.mkdir(parents=True, exist_ok=True)
    files = json.load(urllib.request.urlopen(f"https://archive.org/metadata/{item}", timeout=60))["files"]
    for f in files:
        n = f["name"]
        if not re.search(rx, n) or n.startswith("08(1)"):
            continue
        dst = out / n
        if dst.exists() and dst.stat().st_size == int(f.get("size", 0)):
            continue
        url = f"https://archive.org/download/{item}/{urllib.parse.quote(n)}"
        print("GET", d, n, f.get("size"), flush=True)
        subprocess.run(["curl", "-sSLf", "--retry", "3", "-o", str(dst), url], check=False)
print("DONE", flush=True)
