#!/usr/bin/env bash
# 1) attach scans to typed editions (render pages + renumber typed pages to scan pages)
# 2) OCR the new scanned editions
cd ~/library
mkdir -p scans
attach() {  # id scan.pdf typed.jsonl rule
  local id=$1 pdf=$2 typed=$3 rule=$4
  mkdir -p scans/$id
  n=$(pdfinfo "$pdf" | awk '/^Pages/{print $2}')
  for ((p=1; p<=n; p++)); do
    f=$(printf "scans/%s/p%04d" "$id" "$p")
    [ -s "$f.png" ] || pdftoppm -f $p -l $p -r 200 -gray -png -singlefile "$pdf" "$f"
  done
  python3 maktaba/map_pages.py "$typed" "texts/$id.mapped.jsonl" "$rule"
  echo "attached $id: $n scan pages"
}
attach fadail cand/fadail-imdad-scan.pdf texts/fadail-bok.jsonl "-:2" &
attach zaranjari-hanbali cand/zaranjari-hanbali.pdf texts/zaranjari-hanbali.jsonl "-:2" &
attach khayrat-huda cand/khayrat-huda.pdf texts/khayrat-huda.jsonl "-:0" &
attach tabyid-arqam cand/tabyid-arqam.pdf texts/tabyid-arqam.jsonl "-:0" &
wait
attach uqud cand/uqud-2.pdf texts/uqud.jsonl "-:11"
echo "=== attach done $(date)"

cd ~/library/ocr
for pair in "maqalat-bannuri:maqalat-askzad" "fiqh-azhariyya:fiqh-4157" "uqud-thesis:uqud-3" "khayrat-1324:khayrat-1324" "tabyid-hyd:tabyid-hyd"; do
  id=${pair%%:*}; src=${pair##*:}
  [ -s $id.pdf ] || cp ../cand/$src.pdf $id.pdf
  echo "=== $id start $(date)"
  ../ocr_book.sh $id.pdf 2>&1 | grep -v "^\s*$" | tail -3
  echo "=== $id done $(date)"
done
echo ALLDONE
