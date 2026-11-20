#!/usr/bin/env python3
"""Download the ready-made search index and unpack it, piece by piece, without needing space for the pieces.
    python3 get_index.py <address of the folder that holds index-parts.json> [where to put it, default ./data]
For a GitHub release the address is  https://github.com/<owner>/<repo>/releases/download/<tag>
Every piece and every unpacked file is checked against its checksum. Run it again after a failure: it starts over."""
import hashlib, json, os, sys, tarfile, urllib.request


class Pieces:
    """Reads the pieces one after another as if they were one file, checking each piece's checksum as it passes."""
    def __init__(self, base, parts): self.base = base; self.parts = list(parts); self.r = None; self.h = None; self.cur = None; self.done = 0
    def _next(self):
        if self.cur is not None and self.h.hexdigest() != self.cur["sha256"]: raise IOError("checksum of %s does not match: download damaged" % self.cur["name"])
        if not self.parts: self.cur = None; return False
        self.cur = self.parts.pop(0); self.h = hashlib.sha256(); self.r = urllib.request.urlopen(self.base + "/" + self.cur["name"], timeout=120)
        print("  piece %s (%.2f GB)" % (self.cur["name"], self.cur["bytes"] / 1e9), flush=True); return True
    def read(self, n=-1):
        out = b""
        while n < 0 or len(out) < n:
            if self.r is None and not self._next(): break
            b = self.r.read((n - len(out)) if n >= 0 else 1 << 20)
            if not b: self.r = None; continue
            self.h.update(b); out += b; self.done += len(b)
        if not out and self.cur is not None: self._next()
        return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def main():
    if len(sys.argv) < 2: print(__doc__); return 2
    base = sys.argv[1].rstrip("/"); dest = sys.argv[2] if len(sys.argv) > 2 else "data"; os.makedirs(dest, exist_ok=True)
    m = json.load(urllib.request.urlopen(base + "/index-parts.json", timeout=60))
    print("index: %d pieces, %.2f GB, %d files" % (len(m["parts"]), sum(p["bytes"] for p in m["parts"]) / 1e9, len(m["files"])))
    src = Pieces(base, m["parts"])
    with tarfile.open(fileobj=src, mode="r|") as t:
        for member in t:
            if member.name.startswith("/") or ".." in member.name.split("/"): raise IOError("unsafe path in the archive: " + member.name)
            t.extract(member, dest)
    while src.read(1 << 20): pass                      # the tail of the last piece, so that its checksum is checked too
    bad = [f for f, x in m["files"].items() if not os.path.exists(os.path.join(dest, f)) or os.path.getsize(os.path.join(dest, f)) != x["bytes"] or sha(os.path.join(dest, f)) != x["sha256"]]
    if bad: print("NOT complete, these files are missing or damaged:", bad[:10]); return 1
    print("done: %d files checked, index is in %s" % (len(m["files"]), os.path.abspath(dest))); return 0


if __name__ == "__main__":
    sys.exit(main())
