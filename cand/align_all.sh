#!/usr/bin/env bash
cd ~/library
A="maktaba-venv/bin/python maktaba/align.py"
( echo "## fadail"; $A texts/fadail-bok.jsonl cand/fadail-imdad-scan.pdf 60 200 350 ) > cand/al-fadail.txt 2>&1 &
( echo "## zaranjari-hanbali"; $A texts/zaranjari-hanbali.jsonl cand/zaranjari-hanbali.pdf 60 150 230 ) > cand/al-zar.txt 2>&1 &
( echo "## khayrat-huda"; $A texts/khayrat-huda.jsonl cand/khayrat-huda.pdf 40 100 170 ) > cand/al-khay.txt 2>&1 &
( echo "## uqud"; $A texts/uqud.jsonl cand/uqud-2.pdf 50 200 380 ) > cand/al-uqud.txt 2>&1 &
wait
( echo "## tabyid-arqam"; $A texts/tabyid-arqam.jsonl cand/tabyid-arqam.pdf 30 80 140 ) > cand/al-tab.txt 2>&1 &
( echo "## tanib-1361 vs tanib(1410)"; $A Tanib_ocr/Tanib.jsonl cand/tanib-1361.pdf 60 200 400 ) > cand/al-tanib.txt 2>&1 &
wait
cat cand/al-*.txt
