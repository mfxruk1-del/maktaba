# -*- coding: utf-8 -*-
"""detect(text, book, part, page_num, row_position_in_book) -> (score, flag).
Uses only: passage text, book['death'] (author death, hijri, 99999 unknown), part/page, relative position in the book.
Additive score of a few cheap signs that a "main text" passage is really the editor's front/back matter or study:
 leaders (....), page-number lists (tables of contents / indexes), page references (ص 28), hijri years later than the
 author's death, editor-voice words (المؤلف, الناظم, هذا الكتاب, المبحث ...), and position (front/back of the book)."""
import re
AD = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
CLEAN = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
DOTS = re.compile(r"\.{3,}|…")
REFS = re.compile(r"\(\s*¬?\s*\d+\s*\)|\[\s*\d+\s*\]|(?<=[^\W\d])\d+(?=[\s.,;:،؛)]|$)")     # footnote marks, not counted as numbers
NUMS = re.compile(r"(?<![\d/])\d{1,4}(?![\d/])")
PAGEREF = re.compile(r"(?:\bص|\bج|\bط|\bرقم|\bح)\s*\d+")
YEAR = re.compile(r"(\d{3,4})\s*(?:ه|هـ)(?![ء-ي])")
VOICE = re.compile(r"المؤلف|المصنف|الناظم|المحقق|هذا الكتاب|هذه الرسال|المخطوط|النسخه|نسخه|الطبعه|تحقيق|ترجمته|مقدمه الكتاب|منهج|مؤلفات|مصنفات|المبحث|الدراسه")

def norm(t):
    t = CLEAN.sub("", t or "")
    t = re.sub("[إأآٱ]", "ا", t)
    return t.replace("ى", "ي").replace("ة", "ه")

def features(text, book, part, page_num, pos):
    t = norm(text).translate(AD)
    n = max(1, len(t.split()))
    death = (book or {}).get("death", 99999) or 99999
    t2 = REFS.sub(" ", t)
    f = {}
    f["dots"] = min(len(DOTS.findall(t)), 3)
    f["numd"] = len(NUMS.findall(t2)) / n                 # bare numbers per word (page-number lists, numbered entries)
    f["pageref"] = min(len(PAGEREF.findall(t2)), 3)
    ys = [int(y) for y in YEAR.findall(t)]
    f["year"] = int(bool(ys)); f["lateyear"] = int(death < 99999 and any(death + 2 < y <= 1500 for y in ys))
    f["voice"] = min(len(VOICE.findall(t)), 4)
    f["front"] = int(pos < 0.12 or pos > 0.93)
    f["edge"] = int(pos < 0.03 or pos > 0.97)
    return f

W = dict(dots=0.7, numd=19.78, pageref=2.99, year=0.0, lateyear=0.73, voice=0.0, front=1.29, edge=1.38, bias=-3.76)
THR = 0.0
def score(f, w=None):
    w = w or W
    return w["bias"] + sum(w[k] * f[k] for k in f)

def detect(text, book, part, page_num, row_position_in_book):
    s = score(features(text, book, part, page_num, row_position_in_book))
    return s, s >= THR
