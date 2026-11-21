# -*- coding: utf-8 -*-
"""One call for a whole question: nearby-words AND meaning-search in every scope, merged here on the server into one short list
of BOOKS per scope. The chat then reads one line per book instead of fifty passages per scope.

Why books: the tests of 19-20 Nov 2026 showed that what matters is how many DIFFERENT books with a direct passage a scope reaches,
and that the two tools together reach more books than either alone. Merge = rank fusion of the two lists (1/(60+rank)); copies of
one passage are shown once under the earliest author; a book's other hit pages are listed on its line as page numbers.
Study with the readers' marks: tests/digest_study.py (which merge, how many books) and tests/digest_eval.py (the live endpoint)."""
import time
import semcore

SHORT = {"hanafi": "الفقه الحنفي", "maliki": "الفقه المالكي", "shafii": "الفقه الشافعي", "shafi'i": "الفقه الشافعي", "hanbali": "الفقه الحنبلي",
         "aqida": "العقيدة", "hadith": "كتب السنة", "shuruh": "شروح الحديث", "takhrij": "التخريج والأطراف", "tafsir": "التفسير",
         "usul": "أصول الفقه", "fatawa": "الفتاوى"}
FOUR = ("hanafi", "maliki", "shafii", "hanbali")
ML, MR = semcore.MARK_L, semcore.MARK_R


NOCAT = "scope '%s': this library has no categories; use author:, books:, before:, after: or no scope"


def scopes_of(raw, lib="shamela"):
    """["four"] | ["hanafi", "aqida"] | ["author:الغزالي"] | ["books:21613,5423"] | ["author:ابن عابدين;category:hanafi;before:1300"] | None
    For a library other than Shamela there are no categories, and books: takes that library's own book names (Maktaba ids, Kutub slugs)."""
    out = []
    for x in (raw or [None]):
        if x is None or str(x).strip().lower() in ("", "all", "library"): out.append({"name": "whole library"}); continue
        s = str(x).strip(); k = s.lower()
        if k in ("four", "madhhabs", "four madhhabs"):
            if lib != "shamela": raise KeyError(NOCAT % s)
            out += [{"name": n.capitalize(), "category": SHORT[n]} for n in FOUR]; continue
        d = {"name": s}
        for part in s.split(";"):
            part = part.strip()
            if not part: continue
            key, _, val = part.partition(":"); key = key.strip().lower(); val = val.strip()
            if lib == "maktaba" and (not val or key == "category"):                    # a shelf name, or a kind of text
                v = val or part; d["category"] = {"typed": "typed", "ocr": "OCR", "imported": "imported"}.get(v.lower(), v); continue
            if lib != "shamela" and (not val or key == "category"): raise KeyError(NOCAT % part)
            if not val: d["category"] = SHORT.get(key, part)
            elif key == "category": d["category"] = SHORT.get(val.lower(), val)
            elif key == "author": d["author"] = val
            elif key in ("book", "books") and lib != "shamela": d["books"] = [v.strip() for v in val.split(",") if v.strip()]
            elif key in ("book", "books"): d["shamela_ids"] = [int(v) for v in val.replace(" ", "").split(",") if v]
            elif key == "before": d["died_before"] = int(val)
            elif key == "after": d["died_after"] = int(val)
            else: raise KeyError("scope '%s': use a shortcut, an Arabic category name, author:, books:, before:, after:" % part)
        out.append(d)
    return out[:8]


def ref(x):
    part, page = x.get("part"), x.get("page")
    return "%s/%s" % (part, page) if part is not None and part >= 0 else "p.%s" % page


def ref2(x):
    """Volume/page for a library other than Shamela: a number the source lacks is left out."""
    part, page = x.get("part"), x.get("page")
    if page is None or page < 0: return "p.?"
    return "%s/%s" % (part, page) if part is not None and part >= 0 else "p.%s" % page


OPEN = {"maktaba": 'Open a page: Maktaba\'s get_page(book, page) with the id and the number after "book" and "page"; OCR editions must be checked against the '
                   'scan. Candidates, not quotes.',
        "kutub": 'Open a page: kutub_read_page(book, page) with the slug and the number after "book" and "page". Candidates, not quotes: check the wording with '
                 'check_quote(library="kutub"). Kutub now holds works by Sunni authors only (sorted by machine and by name lists, not checked book by book); typed '
                 'text beside machine-read text. Say who the author is before relying on a page; the owner\'s labels cover only the authors on his list.'}


def cut_match(t, chars):
    """Short quote around the place where the phrase's words met (between the marks)."""
    a = t.find(ML); b = t.find(MR)
    if a < 0 or b < a: return t[:chars].strip() + "…"
    m = t[a + 1:b]; room = max(0, chars - len(m)); lead = t[max(0, a - room // 3):a]
    if a - room // 3 > 0 and " " in lead: lead = lead.split(" ", 1)[1]
    tail = t[b + 1:b + 1 + max(0, room - len(lead))]
    if " " in tail: tail = tail.rsplit(" ", 1)[0]
    return ("…" if a - len(lead) > 0 else "") + lead + "«" + m[:max(chars, 60)] + "»" + tail + "…"


def best_span(t, qtok, chars):
    """For a page found by meaning only: the stretch of about `chars` that holds most of the query's words."""
    words = t.split(" ")
    if not qtok or len(t) <= chars: return t[:chars].strip() + ("…" if len(t) > chars else "")
    hit = [1 if any(k in qtok for k in semcore.toks(w)) else 0 for w in words]
    best = (-1, 0, 0); j = 0; n = 0; h = 0
    for i in range(len(words)):
        while j < len(words) and n + len(words[j]) + 1 <= chars: n += len(words[j]) + 1; h += hit[j]; j += 1
        if h > best[0]: best = (h, i, j)
        if j <= i: j = i + 1; n = 0; h = 0
        else: n -= len(words[i]) + 1; h -= hit[i]
    _, a, b = best
    return ("…" if a > 0 else "") + " ".join(words[a:b]) + ("…" if b < len(words) else "")


def run(s, p, lock, chapter=None, label=None, lib="shamela", scope_fix=None, book_of=None):
    """lib "shamela": as before. Another library (lib, with scope_fix(scope) -> the Searcher's filters and book_of(index id) -> its book):
    no categories, no chapter column, each line ends with that library's own book name and page; a library without vectors
    (s.X is None) runs on nearby-words alone and says so in the first line."""
    t0 = time.time(); other = lib != "shamela"; novec = getattr(s, "X", 0) is None
    phrases = [str(x) for x in (p.get("phrases") or []) if str(x).strip()][:40]
    queries = [str(x) for x in (p.get("queries") or []) if str(x).strip()][:5]
    if not phrases and not queries: return {"error": "give phrases (for nearby-words) and/or queries (for meaning-search)", "digest": ""}
    if novec and not phrases: return {"error": "the %s library has no meaning-search yet: give phrases (nearby-words)" % lib, "digest": ""}
    K = max(1, min(int(p.get("books") or 10), 60)); per = max(5, min(int(p.get("per_tool") or 25), 60)); chars = max(40, min(int(p.get("chars") or 110), 400))
    window = int(p["window"]) if p.get("window") is not None else 8; foot = p.get("footnotes") or "exclude"; preset = p.get("preset") or "auto"
    if other and preset == "auto": preset = "all"            # the other libraries are searched whole unless "classical" is asked for by name
    qtok = set()
    for q in queries: qtok.update(semcore.toks(q))
    out = []; meta = []; items = []
    kind = lambda y: "f" if str(y.get("from") or "").startswith("editor") else "m"
    key = lambda y: "%d|%d|%d|%s" % (y["shamela_id"], y["part"], y["page"], kind(y))
    if novec: out.append("%s library: no meaning-search yet (the index has no vectors); this digest ran on nearby-words alone%s."
                         % (lib.capitalize(), ", the queries were not used" if queries else ""))
    for sc in (scopes_of(p.get("scopes"), lib) if other else scopes_of(p.get("scopes"))):
        kw = {k: sc[k] for k in ("category", "author", "shamela_ids", "died_after", "died_before") if k in sc}
        cand = {}; info = {"scope": sc["name"]}; problems = []; skip = False
        if other and scope_fix:                               # that library's own book names and author spellings -> the index's filters
            fx = scope_fix(sc)
            if fx.get("error"): problems.append(str(fx["error"])[:300]); skip = True
            else:
                kw.pop("author", None); kw.pop("shamela_ids", None); kw.update({k: v for k, v in fx.items() if v})

        def add(x, tool, rank):
            k = (x["shamela_id"], x["shamela_page_id"]); c = cand.get(k)
            if c is None: c = cand[k] = {"x": x, "n": None, "m": None, "met": 0, "ntext": "", "mtext": ""}
            if c[tool] is None or rank < c[tool]: c[tool] = rank
            if tool == "n" and (x.get("phrases_met") or 0) >= c["met"]: c["met"] = x.get("phrases_met") or 0; c["ntext"] = x.get("text") or ""
            if tool == "m" and not c["mtext"]: c["mtext"] = x.get("text") or ""
            if x.get("editor_material"): c["editor"] = True

        if phrases and not skip:
            try:
                with lock: r = s.near(phrases, window=window, preset=preset, footnotes=foot, limit=per, chars=1500, per_book=2, sort="best", group=False, **kw)
                if r.get("error"): problems.append("nearby-words: " + str(r["error"])[:120])
                info["nearby_hits"] = r.get("total_hits"); info["nearby_books"] = r.get("books_with_hits")
                for rank, x in enumerate(r.get("results", []), 1): add(x, "n", rank)
            except Exception as e: problems.append("nearby-words: %r" % (e,))
        if queries and not novec and not skip:
            try:
                with lock: r = s.search_multi(queries, limit=per, chars=1500, footnotes=foot, mode="hybrid", preset=preset, **kw)
                if r.get("error"): problems.append("meaning-search: " + str(r["error"])[:120])
                for rank, x in enumerate(r.get("results", []), 1): add(x, "m", rank)
            except Exception as e: problems.append("meaning-search: %r" % (e,))
        for c in cand.values(): c["score"] = (1.0 / (60 + c["n"]) if c["n"] else 0.0) + (1.0 / (60 + c["m"]) if c["m"] else 0.0)
        order = sorted(cand.values(), key=lambda c: -c["score"])
        plain = [(c["ntext"] or c["mtext"]).replace(ML, "").replace(MR, "") for c in order]
        heads = []
        for g in (semcore.group_same_words(plain) if len(order) > 1 else [[0]] if order else []):          # copies of one passage: once, under the earliest author
            g = sorted(g, key=lambda j: (order[j]["x"].get("died_ah") if order[j]["x"].get("died_ah") is not None else 9999, j)); h = order[g[0]]
            h["same"] = [order[j] for j in g[1:]]; h["gscore"] = max(order[j]["score"] for j in g); heads.append(h)
        heads.sort(key=lambda c: -c["gscore"])
        books = {}; seq = []
        for h in heads:
            b = h["x"]["shamela_id"]
            if b not in books: books[b] = [h]; seq.append(b)
            else: books[b].append(h)
        info.update(books_found=len(seq), books_shown=min(K, len(seq)), pages_merged=len(cand)); meta.append(info)
        name = sc["name"] if "category" not in sc or sc["name"] == sc.get("category") else "%s [%s]" % (sc["name"], sc["category"])
        head = "## %s: " % name + ("nearby-words %s hits in %s books; " % (info.get("nearby_hits"), info.get("nearby_books")) if phrases and not skip else "") + "%d books found, %d shown" % (len(seq), min(K, len(seq)))
        out.append(head + ("  !! " + " | ".join(problems) if problems else ""))
        for n, b in enumerate(seq[:K], 1):
            h = books[b][0]; x = h["x"]; tags = "+".join(t for t in ("N%d" % h["met"] if h["n"] else "", "M" if h["m"] else "") if t)
            if kind(x) == "f": tags += " footnote"
            if h.get("editor"): tags += " editor?"
            lab = label(x["shamela_id"]) if label else None
            if lab: tags += " label:" + lab
            died = x.get("died_ah"); quote = cut_match(h["ntext"], chars) if h["n"] else best_span(h["mtext"], qtok, chars)
            ch = chapter(x["shamela_id"], x["shamela_page_id"]) if chapter else None
            if other:
                bk = (book_of(x["shamela_id"]) if book_of else None) or {}; name = lambda q: (book_of(q["shamela_id"]) or {}).get("kutub_slug") or (book_of(q["shamela_id"]) or {}).get("maktaba_id")
                line = "%d. %s | %s (%s) | %s | %s | %s | book %s page %d" % (n, (x.get("title") or "")[:48], (bk.get("author_ar") or x.get("author") or "")[:30],
                                                                         "d.%s" % died if died is not None else "d.?", ref2(x), tags, quote.replace("\n", " "), name(x), x["shamela_page_id"])
            else:
                line = "%d. %s | %s (%s) | %s | %s | %s | %s | id %d:%d" % (n, (x.get("title") or "")[:48], (x.get("author") or "")[:30], "d.%s" % died if died is not None else "modern",
                                                                     ref(x), tags, (ch or "-")[:90], quote.replace("\n", " "), x["shamela_id"], x["shamela_page_id"])
            same = [o for hh in books[b] for o in hh.get("same", [])]
            others = books[b][1:] + [o for o in same if o["x"]["shamela_id"] == b]; same = [o for o in same if o["x"]["shamela_id"] != b]      # a copy inside the same book is just another page of it
            also = ["%s#%d" % (ref2(o["x"]) if other else ref(o["x"]), o["x"]["shamela_page_id"]) for o in others[:5]]
            if also: line += " | also " + ", ".join(also) + (" +%d" % (len(others) - 5) if len(others) > 5 else "")
            if same and other:
                line += " | same words: " + "; ".join("%s %s (%s%s) book %s page %d" % ((o["x"].get("title") or "")[:32], ref2(o["x"]), ((book_of(o["x"]["shamela_id"]) or {}).get("author_ar") or o["x"].get("author") or "")[:18],
                        " d.%s" % o["x"]["died_ah"] if o["x"].get("died_ah") is not None else "", name(o["x"]), o["x"]["shamela_page_id"]) for o in same[:4]) + (" +%d" % (len(same) - 4) if len(same) > 4 else "")
            elif same:
                line += " | same words: " + "; ".join("%s %s (%s%s) id %d:%d" % ((o["x"].get("title") or "")[:32], ref(o["x"]), (o["x"].get("author") or "")[:18],
                        " d.%s" % o["x"]["died_ah"] if o["x"].get("died_ah") is not None else "", o["x"]["shamela_id"], o["x"]["shamela_page_id"]) for o in same[:4]) + (" +%d" % (len(same) - 4) if len(same) > 4 else "")
            out.append(line)
            if p.get("items"):
                items.append({"scope": sc["name"], "rank": n, "shamela_id": b, "line": key(x), "also": [key(o["x"]) for o in others], "same": [key(o["x"]) for o in same],
                              "by": ("n" if h["n"] else "") + ("m" if h["m"] else "")})
        if len(seq) > K: out.append("(+%d more books in this scope: books=%d shows them)" % (len(seq) - K, min(60, len(seq))))
        elif not seq and not skip: out.append("(nothing found here; that is not proof of absence: try other words)")
    out.append(OPEN[lib] if other else "Open a page: shamela_read_page(shamela_id, page_id) with the two numbers after \"id\". Candidates, not quotes.")
    res = {"digest": "\n".join(out), "scopes": meta, "ms": round((time.time() - t0) * 1000)}
    if other: res["library"] = lib
    if p.get("items"): res["items"] = items
    return res
