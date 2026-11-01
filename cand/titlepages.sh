#!/usr/bin/env bash
# OCR the first pages of candidate PDFs to read their title/edition pages.
cd "$(dirname "$0")"; mkdir -p tp
M=$(ls ~/.local/share/htrmopo/*/arabic_best.mlmodel | head -1)
list=()
for b in "$@"; do for p in 1 2 3 4 5; do
  [ -s tp/$b-$p.png ] || pdftoppm -f $p -l $p -r 200 -gray -png -singlefile $b.pdf tp/$b-$p
  [ -s tp/$b-$p.txt ] || list+=("$b-$p")
done; done
for j in 0 1 2 3; do
  ( args=(); for ((i=j; i<${#list[@]}; i+=4)); do args+=(-i "tp/${list[$i]}.png" "tp/${list[$i]}.txt"); done
    [ ${#args[@]} -gt 0 ] && ~/kraken/bin/kraken "${args[@]}" segment -bl ocr -m "$M" > tp/log$j 2>&1 ) &
done; wait
for f in tp/*.txt; do
  ~/kraken/bin/python -c '
import sys,re
swap=str.maketrans("()[]{}«»<>",")(][}{»«><")
L=re.compile(r"[0-9٠-٩۰-۹](?:[0-9٠-٩۰-۹/.,:\-]*[0-9٠-٩۰-۹])?|[A-Za-z]+")
t=[L.sub(lambda m:m.group(0)[::-1],l[::-1].translate(swap)) for l in open(sys.argv[1],encoding="utf-8").read().splitlines()]
print("==",sys.argv[1]); print(" | ".join(x.strip() for x in t if x.strip())[:400])' "$f"
done
