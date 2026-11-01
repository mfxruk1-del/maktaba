#!/usr/bin/env bash
# probe.sh name item [file-substring]  -> download the item's main PDF/EPUB (if missing) and report quality
cd "$(dirname "$0")"
name="$1"; item="$2"; want="${3:-}"
ext="${name##*.}"
if [ ! -s "$name" ]; then
  f=$(curl -sS "https://archive.org/metadata/$item" | python3 -c '
import json,sys
ext,want=sys.argv[1],sys.argv[2]
fs=[f["name"] for f in json.load(sys.stdin)["files"] if f["name"].endswith("."+ext) and not f["name"].endswith(("_text.pdf","_lcp.epub"))]
fs=[f for f in fs if want in f] or fs
print(max(fs,key=len) if fs else "")' "$ext" "$want")
  [ -n "$f" ] || { echo "$name: no .$ext in $item"; exit; }
  url="https://archive.org/download/$item/$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$f")"
  curl -sSLf -o "$name" "$url" || { echo "$name: DOWNLOAD FAILED"; exit; }
fi
case "$name" in
  *.pdf)
    pages=$(pdfinfo "$name" 2>/dev/null | awk '/^Pages/{print $2}')
    mid=$(( pages / 2 ))
    img=$(pdfimages -list -f $mid -l $mid "$name" 2>/dev/null | awk 'NR==3{print $4"x"$5, $6, $13"dpi"}')
    txt=$(pdftotext -f $mid -l $mid "$name" - 2>/dev/null | tr -d '[:space:]' | wc -c)
    echo "$name: $pages pages | mid-page image $img | text chars on mid page: $txt" ;;
  *.epub)
    n=$(unzip -l "$name" | grep -c -E '\.x?html')
    t=$(unzip -p "$name" '*.xhtml' '*.html' 2>/dev/null | sed 's/<[^>]*>//g' | tr -d '[:space:]' | wc -c)
    echo "$name: epub html files $n, text chars $t, images $(unzip -l "$name" | grep -c -E '\.(jpe?g|png)')" ;;
esac
