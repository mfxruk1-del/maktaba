# -*- coding: utf-8 -*-
"""chapter(con, shamela_id, shamela_page_id): where a page sits in its book, as "كتاب ... > باب ... > فصل ...", from the book's table
of contents in the page store. The chain logic is the one the chapter-names trial used and checked (proto/crumbs build_toc): the
dataset records a parent only one step deep, so below that the level of a heading is read from its first word (kitab / bab / fasl)."""
import re, json, zlib, bisect, collections, threading
TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]"); TAG = re.compile(r"<[^>]+>"); FIRSTW = re.compile("[ء-ي]+")
CACHE = collections.OrderedDict(); MAX_BOOKS = 300; LOCK = threading.Lock()


def clean(t): return re.sub(r"\s+", " ", TASHKEEL.sub("", TAG.sub(" ", t or ""))).strip()


def to_int(v, d=-1):
    try: return int(v)
    except Exception: return d


def first_word(title):
    m = FIRSTW.search(title); w = m.group(0) if m else ""
    if w.startswith("ال") and len(w) > 4: w = w[2:]
    return w.replace("أ", "ا")


def level_of(title):
    w = first_word(title)
    return 1 if w == "كتاب" else 2 if w in ("باب", "ابواب") else 3 if w in ("فصل", "فصول") else 4


def build(rows):
    """toc rows -> (page ids in reading order, the chain of headings open at each entry)."""
    rows = sorted(rows, key=lambda r: r.get("shamela_title_id") or 0); by = {r["title_id"]: r for r in rows}; last = {}; T = {}
    for r in rows:
        T[r["title_id"]] = clean(r.get("title_text")); p = r.get("parent_id")
        if p is not None and p in by: last[p] = max(last.get(p, -1), r.get("shamela_title_id") or 0)
    rw = collections.Counter(first_word(T[t]) for t in last); top_word = rw.most_common(1)[0][0] if rw else ""
    pages = []; chains = []; K = c = None; sub = ["", "", "", ""]; run = 0
    for r in rows:
        tid = r["title_id"]; sid = r.get("shamela_title_id") or 0; p = r.get("parent_id"); t = T[tid]
        if tid in last: K, c, sub = tid, None, ["", "", "", ""]
        elif p is not None and p in by: K, c, sub = p, tid, ["", "", "", ""]
        else:
            if K is not None and sid >= last[K]:
                w = first_word(t)
                if w and (w == "كتاب" or w == first_word(T[K]) or w == top_word): K, c, sub = None, None, ["", "", "", ""]
            if t:
                lv = level_of(t); sub[lv - 1] = t
                for j in range(lv, 4): sub[j] = ""
        run = max(run, to_int(r.get("page_id"), 0)); pages.append(run)
        chains.append([x for x in ([T[K]] if K is not None else []) + ([T[c]] if c is not None else []) + sub if x])
    return pages, chains


def _book(con, sid):
    with LOCK:
        if sid in CACHE: CACHE.move_to_end(sid); return CACHE[sid]
    row = con.execute("SELECT data FROM toc WHERE shamela_id=?", (sid,)).fetchone(); val = ([], [])
    if row is not None and row[0]:
        try: val = build([json.loads(l) for l in zlib.decompress(row[0]).decode("utf-8").splitlines() if l.strip()])
        except Exception: val = ([], [])
    with LOCK:
        CACHE[sid] = val
        while len(CACHE) > MAX_BOOKS: CACHE.popitem(last=False)
    return val


def chapter(con, shamela_id, shamela_page_id, each=60):
    sid = int(shamela_id); r = con.execute("SELECT page_id FROM pages WHERE shamela_id=? AND shamela_page_id=?", (sid, int(shamela_page_id))).fetchone()
    if r is None: return None
    pages, chains = _book(con, sid); i = bisect.bisect_right(pages, r[0]) - 1
    if i < 0 or not chains[i]: return None
    return " > ".join(x if len(x) <= each else x[:each].rsplit(" ", 1)[0] + "…" for x in chains[i])
