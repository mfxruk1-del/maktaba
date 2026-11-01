#!/usr/bin/env bash
# ocr_book.sh — OCR an Arabic PDF with Kraken + the OpenITI printed-Arabic model.
# Usage:  ./ocr_book.sh book.pdf [first_page] [last_page] [jobs]
# Output: <book>_ocr/pages/p0001.txt ...  (one clean text file per PDF page)
#         <book>_ocr/<book>.jsonl         ({"page": n, "text": "..."} per line, for the library index)
# Needs:  poppler-utils (pdftoppm, pdfinfo), Kraken in ~/kraken, model downloaded.
set -euo pipefail

PDF="$1"
KRAKEN="${KRAKEN:-$HOME/kraken/bin/kraken}"
PY="${PY:-$HOME/kraken/bin/python}"
MODEL="${MODEL:-$(ls "$HOME"/.local/share/htrmopo/*/arabic_best.mlmodel | head -1)}"
LAST_DEFAULT=$(pdfinfo "$PDF" | awk '/^Pages:/{print $2}')
FIRST="${2:-1}"; LAST="${3:-$LAST_DEFAULT}"
JOBS="${4:-$(nproc)}"

NAME=$(basename "$PDF" .pdf)
OUT="${NAME}_ocr"; IMG="$OUT/img"; RAW="$OUT/raw"; PAGES="$OUT/pages"
mkdir -p "$IMG" "$RAW" "$PAGES"

echo "Model: $MODEL"
echo "Pages $FIRST-$LAST of $LAST_DEFAULT, $JOBS parallel jobs"

# 1. Render pages to 300 dpi grayscale PNG (skips pages already rendered)
for ((p=FIRST; p<=LAST; p++)); do
  f=$(printf "%s/p%04d.png" "$IMG" "$p")
  [ -f "$f" ] || pdftoppm -f "$p" -l "$p" -r 300 -gray -png -singlefile "$PDF" "${f%.png}"
done

# 2. OCR in parallel; each job loads the model once for its whole batch.
#    Pages that already have output are skipped, so the script can be re-run after an interruption.
todo=()
for ((p=FIRST; p<=LAST; p++)); do
  b=$(printf "p%04d" "$p")
  [ -s "$RAW/$b.txt" ] || todo+=("$b")
done
echo "${#todo[@]} pages to OCR"
if [ "${#todo[@]}" -gt 0 ]; then
  rm -f "$OUT"/batch_*                      # clear lists/logs left by an earlier run
  printf "%s\n" "${todo[@]}" | split -n "r/$JOBS" - "$OUT/batch_"
  for bf in "$OUT"/batch_??; do             # only the list files, never the .log files
    (
      args=()
      while read -r b; do args+=(-i "$IMG/$b.png" "$RAW/$b.txt"); done < "$bf"
      "$KRAKEN" "${args[@]}" segment -bl ocr -m "$MODEL" > "$bf.log" 2>&1 || echo "batch $bf failed, see $bf.log"
    ) &
  done
  wait
  rm -f "$OUT"/batch_??
fi

# 3. Clean up: Kraken writes each line in visual (reversed) order with mirrored brackets
#    and decomposed hamza. Reverse lines, swap bracket pairs, NFC-normalise.
"$PY" -I - "$RAW" "$PAGES" "$OUT/$NAME.jsonl" "$FIRST" "$LAST" <<'EOF'
import sys, json, re, unicodedata, pathlib
raw, pages, jsonl, first, last = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
swap = str.maketrans("()[]{}«»<>", ")(][}{»«><")
persian = str.maketrans({"ی": "ي", "ک": "ك"})   # model sometimes emits Persian letter forms
# Reversing a visual-order line also reverses left-to-right runs (numbers like 15/474, Latin words);
# flip those runs back so they read correctly again.
LTR = re.compile(r"[0-9٠-٩۰-۹](?:[0-9٠-٩۰-۹/.,:\-]*[0-9٠-٩۰-۹])?|[A-Za-z]+")
def fix_line(l):
    l = l[::-1].translate(swap)
    return LTR.sub(lambda m: m.group(0)[::-1], l)
with open(jsonl, "w", encoding="utf-8") as out:
    for p in range(first, last + 1):
        src = pathlib.Path(raw, f"p{p:04d}.txt")
        if not src.exists():
            print(f"missing page {p}"); continue
        lines = [unicodedata.normalize("NFC", fix_line(l)).translate(persian).strip()
                 for l in src.read_text(encoding="utf-8").splitlines()]
        text = "\n".join(l for l in lines if l)
        pathlib.Path(pages, f"p{p:04d}.txt").write_text(text + "\n", encoding="utf-8")
        out.write(json.dumps({"page": p, "text": text}, ensure_ascii=False) + "\n")
print("done:", jsonl)
EOF
