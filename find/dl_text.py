import json, urllib.request, urllib.parse, re, subprocess, pathlib, time
base = pathlib.Path.home() / "library" / "cand"
for d, item in [("muhit-radawi", "20250905_20250905_1028"), ("dhakhira", "15_20200929_202009")]:
    out = base / d; out.mkdir(parents=True, exist_ok=True)
    for f in json.load(urllib.request.urlopen(f"https://archive.org/metadata/{item}", timeout=60))["files"]:
        n = f["name"]
        if not n.endswith("_text.pdf") or n.startswith("08(1)"): continue
        dst = out / n
        if dst.exists() and dst.stat().st_size == int(f["size"]): continue
        for a in range(6):
            r = subprocess.run(["curl", "-sSLf", "-o", str(dst), f"https://archive.org/download/{item}/{urllib.parse.quote(n)}"])
            if r.returncode == 0: print("ok", d, n, flush=True); break
            time.sleep(15 * (a + 1))
        else: print("FAILED", d, n, flush=True)
print("DONE")
