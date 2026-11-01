#!/usr/bin/env bash
# OCR the first and last fihris page of each downloaded Tatarkhaniyya volume
cd ~/library/find/tat_fihris
for f in ~/library/cand/tatarkhaniyya/Fattatar[0-2][0-9].pdf; do
  n=$(basename $f .pdf); [ -s "${n}_done" ] && continue
  read fp last < <(~/library/maktaba-venv/bin/python -c "
import pymupdf;d=pymupdf.open('$f');t=d.get_toc();print([x[2] for x in t if 'الفهرس' in x[1]][0], d.page_count)" 2>/dev/null)
  ln -sf $f $n.pdf
  ~/library/ocr_book.sh $n.pdf $fp $((fp+1)) 2 > $n.log 2>&1
  ~/library/ocr_book.sh $n.pdf $((last-1)) $last 2 >> $n.log 2>&1
  echo "$fp $last" > ${n}_done
done
echo FIHRIS_DONE
