#!/usr/bin/env bash
# Cut the finished search index into pieces that fit GitHub Releases (each file must be under 2 GiB; no limit on the total).
#   ./make_index_parts.sh ~/semsearch/data /some/folder/with/13GB/free [piece size, default 1900M]
# Makes: shamela-index.tar.part00, part01, ...  and  index-parts.json (the list of pieces with their checksums, and a checksum of
# every file inside, which get_index.py checks after unpacking). Upload all of them to one release.
set -euo pipefail
DATA="$(cd "$1" && pwd)"; OUT="$2"; SIZE="${3:-1900M}"; mkdir -p "$OUT"; cd "$OUT"; rm -f shamela-index.tar.part* index-parts.json
tar -c -C "$DATA" . | split -b "$SIZE" -d -a 2 - shamela-index.tar.part
python3 - "$DATA" <<'PY'
import hashlib, json, os, sys
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()
data = sys.argv[1]; parts = sorted(f for f in os.listdir(".") if f.startswith("shamela-index.tar.part"))
files = {os.path.relpath(os.path.join(d, f), data): {"bytes": os.path.getsize(os.path.join(d, f)), "sha256": sha(os.path.join(d, f))} for d, _, fs in os.walk(data) for f in fs}
json.dump({"parts": [{"name": p, "bytes": os.path.getsize(p), "sha256": sha(p)} for p in parts], "files": files}, open("index-parts.json", "w"), indent=1)
print("pieces:", len(parts), "| files inside:", len(files), "| total GB: %.2f" % (sum(os.path.getsize(p) for p in parts) / 1e9))
PY
