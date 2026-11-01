#!/usr/bin/env bash
# vps_queue.sh — the VPS's share of the OCR queue: works from the FRONT of ocr_queue.json,
# marks each book it takes with ocr/<id>_ocr/.vps (remote workers then skip it), and leaves books
# that a remote worker uploaded pages to in the last hour. Re-runnable: done pages are skipped.
cd ~/library/ocr || exit 1
TRIED=""
while true; do
  id=$(TRIED="$TRIED" python3 - <<'PY'
import json, pathlib, time, subprocess, os
tried = os.environ.get('TRIED', '').split()
q = json.load(open("../ocr_queue.json"))
for e in q:
    i = e["id"]; d = pathlib.Path(f"{i}_ocr"); raw = d / "raw"
    pdf = pathlib.Path(f"{i}.pdf")
    if i in tried or not pdf.exists(): continue
    n = int([l for l in subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout.splitlines() if l.startswith("Pages:")][0].split()[1])
    files = list(raw.glob("p*.txt")) if raw.exists() else []
    if len([f for f in files if f.stat().st_size > 0]) >= n: continue
    if not (d / ".vps").exists() and any(time.time() - f.stat().st_mtime < 3600 for f in files): continue
    print(i); break
PY
)
  [ -z "$id" ] && { echo "queue empty for the VPS"; break; }
  echo "=== $(date -Is) $id"
  TRIED="$TRIED $id"
  mkdir -p "${id}_ocr" && touch "${id}_ocr/.vps"
  ~/library/ocr_book.sh "$id.pdf" 1 "" 4 2>&1 | tail -3 || true
done
