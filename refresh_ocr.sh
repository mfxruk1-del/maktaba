#!/usr/bin/env bash
# refresh_ocr.sh — fold newly OCR'd pages (VPS + Kaggle/Colab workers) into the library index.
# Re-assembles every multi-volume Hanafi volume whose raw page count grew, then rebuilds and restarts only if something changed.
cd ~/library || exit 1
changed=()
for d in ocr/dhakhira-*_ocr ocr/tatarkhaniyya-*_ocr ocr/muhit-radawi-*_ocr; do
  [ -d "$d/raw" ] || continue
  id=$(basename "$d" _ocr)
  n=$(find "$d/raw" -name 'p*.txt' -size +0 | wc -l)
  have=$( [ -f "$d/$id.jsonl" ] && wc -l < "$d/$id.jsonl" || echo 0)
  [ "$n" -gt "$have" ] && changed+=("$id")
done
[ ${#changed[@]} -eq 0 ] && { echo "$(date -Is) nothing new"; exit 0; }
echo "$(date -Is) refreshing: ${changed[*]}"
~/kraken/bin/python -I assemble.py "${changed[@]}" && python3 catalog.py \
  && (cd maktaba && ../maktaba-venv/bin/python build_index.py .. | tail -1) && sudo systemctl restart maktaba
