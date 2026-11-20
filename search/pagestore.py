# -*- coding: utf-8 -*-
"""The server's own copy of every Shamela book (pages/pages.sqlite3, filled by pages/ingest.py from the Hugging Face dataset
AuthenticIlm/Shamela4_Full_DB): read a page, check a quote, list a book's headings. No PC needed.
Text comes back as the dataset holds it (with its diacritics); only the markup is taken off. Footnotes are kept apart from the body."""
import os, re, json, zlib, sqlite3
import semcore

DB = os.environ.get("SEM_PAGES", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages", "pages.sqlite3"))
TAG = re.compile(r"<[^>]+>"); HEAD = re.compile(r"<span data-type=.title.[^>]*>(.*?)</span>", re.S); LETTERS = re.compile("[ء-ي]+")


def connect():
    if not os.path.exists(DB): raise RuntimeError("the page store is not on this server yet")
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True); con.row_factory = sqlite3.Row
    return con


def render(raw):
    """Markup off, headings on their own line between « » marks kept as text, line breaks kept."""
    if not raw: return ""
    t = HEAD.sub(lambda m: "\n" + TAG.sub("", m.group(1)).strip() + "\n", raw)
    t = re.sub(r"<br\s*/?>|</tr>|</p>", "\n", t); t = TAG.sub(" ", t).replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{2,}", "\n", t).strip()


def _txt(b): return zlib.decompress(b).decode("utf-8") if b else ""


def book(con, shamela_id):
    r = con.execute("SELECT shamela_id, title, author, death, cat, pages, toc_entries FROM books WHERE shamela_id=?", (int(shamela_id),)).fetchone()
    if r is None: return None
    return {"shamela_id": r["shamela_id"], "title": r["title"], "author": r["author"], "died_ah": None if r["death"] is None or r["death"] >= 9000 else r["death"],
            "category": r["cat"], "pages": r["pages"], "headings": r["toc_entries"]}


def missing(con, shamela_id):
    n = con.execute("SELECT count(*) FROM books").fetchone()[0]
    return {"error": "book %s is not in the server's page store (%d books are stored; the search index has 8,587). If the copy is still running, "
                     "read it with the Shamela connector on the PC for now." % (shamela_id, n)}


def locate(con, shamela_id, page_id=None, part=None, page=None):
    """Rows for one place in a book: by Shamela page id, or by printed volume and page (several rows can carry one printed number)."""
    sid = int(shamela_id)
    if page_id is not None:
        return con.execute("SELECT * FROM pages WHERE shamela_id=? AND shamela_page_id=?", (sid, int(page_id))).fetchall()
    if page is None: return []
    if part is None: return con.execute("SELECT * FROM pages WHERE shamela_id=? AND page_num=? ORDER BY shamela_page_id", (sid, int(page))).fetchall()
    return con.execute("SELECT * FROM pages WHERE shamela_id=? AND part=? AND page_num=? ORDER BY shamela_page_id", (sid, int(part), int(page))).fetchall()


def _page(r, chars, around=None, radius=600):
    body = render(_txt(r["body"])); foot = render(_txt(r["foot"])); out = {"shamela_page_id": r["shamela_page_id"], "part": r["part"], "page": r["page_num"]}
    if around:
        hit = find(body, around)
        if hit and hit["exact"]:
            a = max(0, hit["start_char"] - radius); b = min(len(body), hit["end_char"] + radius)
            out["body"] = ("… " if a > 0 else "") + body[a:b] + (" …" if b < len(body) else ""); out["body_is_excerpt_around_the_phrase"] = True
        else:
            out["body"] = body[:chars]; out["phrase_not_found_on_this_page"] = True
    else: out["body"] = body[:chars]
    if not around and len(body) > chars: out["body_cut_at"] = chars; out["body_length"] = len(body)
    out["footnotes"] = foot[:max(400, chars // 2)] if foot else None
    if foot and len(foot) > max(400, chars // 2): out["footnotes_cut"] = True
    return out


def read(con, shamela_id, page_id=None, part=None, page=None, context=0, chars=6000, around=None):
    b = book(con, shamela_id)
    if b is None: return missing(con, shamela_id)
    rows = locate(con, shamela_id, page_id, part, page)
    if not rows: return {"error": "no such page in this book", "book": b, "hint": "give page_id (the Shamela page id, shamela_page_id in search results) or part and page (printed)"}
    r = rows[0]; spid = r["shamela_page_id"]; context = max(0, min(int(context), 3)); chars = max(300, min(int(chars), 20000))
    lo = con.execute("SELECT * FROM pages WHERE shamela_id=? AND shamela_page_id<? ORDER BY shamela_page_id DESC LIMIT ?", (b["shamela_id"], spid, max(context, 1))).fetchall()[::-1]
    hi = con.execute("SELECT * FROM pages WHERE shamela_id=? AND shamela_page_id>? ORDER BY shamela_page_id LIMIT ?", (b["shamela_id"], spid, max(context, 1))).fetchall()
    pages = [_page(x, chars) for x in lo[-context:]] if context else []
    pages.append(dict(_page(r, chars, around), asked_for=True)); pages += [_page(x, chars) for x in hi[:context]] if context else []
    out = {"book": b, "pages": pages, "previous_page_id": lo[-1]["shamela_page_id"] if lo else None, "next_page_id": hi[0]["shamela_page_id"] if hi else None,
           "source": "the server's copy of Shamela (dataset text, markup removed, diacritics as in the dataset)"}
    if len(rows) > 1: out["note"] = "%d pages carry this printed number: page ids %s; the first is shown" % (len(rows), [x["shamela_page_id"] for x in rows][:12])
    return out


def _words(text):
    """[(normalised letters, start, end)] for every word that holds Arabic letters."""
    out = []
    for m in re.finditer(r"\S+", text):
        k = "".join(LETTERS.findall(semcore.norm(m.group(0))))
        if k: out.append((k, m.start(), m.end()))
    return out


def find(text, quote):
    """Where the quote's words stand in the text, ignoring diacritics, punctuation, hamza / ya / ta-marbuta spelling.
    Returns {"exact": True, start_char, end_char, "words": n} or, failing that, the longest run of the quote's words found in a row."""
    W = _words(text); Q = [k for k, _, _ in _words(quote)]
    if not W or not Q: return None
    keys = [k for k, _, _ in W]; n, m = len(keys), len(Q)
    first = Q[0]
    for i in range(n - m + 1):
        if keys[i] == first and keys[i:i + m] == Q: return {"exact": True, "start_char": W[i][1], "end_char": W[i + m - 1][2], "words": m}
    best = (0, 0, 0); prev = [0] * (m + 1)                    # longest common run of words
    for i in range(1, n + 1):
        cur = [0] * (m + 1); ki = keys[i - 1]
        for j in range(1, m + 1):
            if ki == Q[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best[0]: best = (cur[j], i - cur[j], j - cur[j])
        prev = cur
    if best[0] == 0: return {"exact": False, "run": 0, "words": m}
    return {"exact": False, "run": best[0], "words": m, "start_char": W[best[1]][1], "end_char": W[best[1] + best[0] - 1][2], "quote_word_from": best[2] + 1}


def check(con, shamela_id, quote, page_id=None, part=None, page=None):
    b = book(con, shamela_id)
    if b is None: return missing(con, shamela_id)
    nq = len(_words(quote))
    if nq < 3: return {"error": "give at least three Arabic words to check"}
    sid = b["shamela_id"]
    if page_id is None and page is None:                     # no page given: look through the whole book
        hits = []; best = None
        for r in con.execute("SELECT shamela_page_id, part, page_num, body, foot FROM pages WHERE shamela_id=? ORDER BY shamela_page_id", (sid,)):
            for where, raw in (("body", r["body"]), ("footnotes", r["foot"])):
                if not raw: continue
                t = render(_txt(raw)); h = find(t, quote)
                if not h: continue
                e = {"shamela_page_id": r["shamela_page_id"], "part": r["part"], "page": r["page_num"], "in": where}
                if h["exact"]: hits.append(dict(e, words_on_the_page=t[h["start_char"]:h["end_char"]]))
                elif h["run"] and (best is None or h["run"] > best[0]): best = (h["run"], dict(e, longest_run_of_words=h["run"], of=h["words"], words_on_the_page=t[h["start_char"]:h["end_char"]]))
            if len(hits) >= 8: break
        out = {"book": b, "found": bool(hits), "searched": "the whole book", "places": hits}
        if not hits and best: out["closest"] = best[1]
        return out
    rows = locate(con, sid, page_id, part, page)
    if not rows: return {"error": "no such page in this book", "book": b}
    spid = rows[0]["shamela_page_id"]
    win = con.execute("SELECT shamela_page_id, part, page_num, body, foot FROM pages WHERE shamela_id=? AND shamela_page_id BETWEEN ? AND ? ORDER BY shamela_page_id", (sid, spid - 1, spid + 1)).fetchall()
    best = None
    for where in ("body", "foot"):                            # the page itself first, then running across the page before and after
        parts = [(r, render(_txt(r[where]))) for r in win if r[where]]
        order = [p for p in parts if p[0]["shamela_page_id"] == spid] + [None]
        for single in order:
            if single is not None: text = single[1]; spans = [(0, single[0])]
            else:
                text = ""; spans = []
                for r, t in parts: spans.append((len(text), r)); text += t + "\n"
            h = find(text, quote) if text else None
            if not h: continue
            def page_of(pos): return [r for s, r in spans if s <= pos][-1]
            if h["exact"]:
                r0 = page_of(h["start_char"]); r1 = page_of(h["end_char"] - 1)
                return {"book": b, "found": True, "in": "body" if where == "body" else "footnotes (the editor's words)", "shamela_page_id": r0["shamela_page_id"], "part": r0["part"],
                        "page": r0["page_num"], "runs_on_to_page_id": r1["shamela_page_id"] if r1["shamela_page_id"] != r0["shamela_page_id"] else None,
                        "on_the_page_asked_for": r0["shamela_page_id"] == spid, "words_on_the_page": text[h["start_char"]:h["end_char"]], "words_checked": h["words"]}
            if h["run"] and (best is None or h["run"] > best["longest_run_of_words"]):
                r0 = page_of(h["start_char"])
                best = {"longest_run_of_words": h["run"], "of": h["words"], "starting_at_quote_word": h["quote_word_from"], "in": "body" if where == "body" else "footnotes",
                        "shamela_page_id": r0["shamela_page_id"], "words_on_the_page": text[h["start_char"]:h["end_char"]]}
    return {"book": b, "found": False, "searched": "page id %d and the page before and after" % spid, "closest": best,
            "note": "not found as an unbroken run of words; the wording may differ, or stand on another page"}


def contents(con, shamela_id, query=None, limit=60):
    b = book(con, shamela_id)
    if b is None: return missing(con, shamela_id)
    row = con.execute("SELECT data FROM toc WHERE shamela_id=?", (b["shamela_id"],)).fetchone()
    if row is None or not row["data"]: return {"book": b, "headings": [], "note": "this book has no table of contents in the dataset"}
    rows = [json.loads(l) for l in zlib.decompress(row["data"]).decode("utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: r.get("shamela_title_id") or 0); by = {r["title_id"]: r for r in rows}
    pid = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT page_id, shamela_page_id, part, page_num FROM pages WHERE shamela_id=?", (b["shamela_id"],))}
    q = [k for k, _, _ in _words(query)] if query else []; out = []; total = 0
    for r in rows:
        title = re.sub(r"\s+", " ", TAG.sub(" ", r.get("title_text") or "")).strip()
        if q:
            keys = [k for k, _, _ in _words(title)]
            if not all(any(x in k for k in keys) for x in q): continue
        total += 1
        if len(out) >= limit: continue
        p = pid.get(r.get("page_id")); par = by.get(r.get("parent_id"))
        e = {"heading": title, "shamela_page_id": p[0] if p else None, "part": p[1] if p else None, "page": p[2] if p else None}
        if par: e["under"] = re.sub(r"\s+", " ", par.get("title_text") or "").strip()
        out.append(e)
    return {"book": b, "matching_headings": total, "shown": len(out), "headings": out}
