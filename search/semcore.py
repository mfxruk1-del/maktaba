# -*- coding: utf-8 -*-
"""Search core for the Shamela meaning-search index. Used by the build self-test and by the server.

Data folder: books.json, meta.npy (int32 [N,8]: book_id, shamela_id, page_id, shamela_page_id, part, page_num,
kind 0 main text / 1 editor's footnote, passage_no), vec256.i8 (N x 256 int8), texts.bin + text_offsets.npy, kw/ (tantivy).
"""
import json, os, re, time, zlib
import numpy as np

MODEL = "Omartificial-Intelligence-Space/Arabic-Triplet-Matryoshka-V2"
DIM = 256
BLOCK = 256
TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
WORD = re.compile("[ء-ي]+")


def norm(t):
    t = TASHKEEL.sub("", t or "")
    t = re.sub("[إأآٱ]", "ا", t)
    return t.replace("ى", "ي").replace("ة", "ه")


def stem(w):
    for p in ("وال", "بال", "فال", "كال", "لل", "ال"):
        if w.startswith(p) and len(w) - len(p) >= 3: return w[len(p):]
    if w[:1] in "وف" and len(w) >= 5: return w[1:]
    return w


def toks(t):
    return [stem(w) for w in WORD.findall(norm(t)) if len(w) > 1]


def merge_ranges(ranges):
    out = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1]: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return out

import itertools
from concurrent.futures import ThreadPoolExecutor

CLASSICAL_BEFORE = 1300      # the "classical" preset: author died in or before this hijri year (about 1883 CE)
DEFAULT_CAP = 3              # passages one book may hold before other books get their turn (0 = no cap)
MARK_L, MARK_R = chr(0x27EA), chr(0x27EB)


def apply_preset(preset, shamela_ids, author, died_after, died_before):
    """Return (died_before, label). "auto" means classical unless the caller already chose books, an author or dates."""
    p = (preset or "auto").lower()
    if p not in ("auto", "classical", "all"): raise KeyError("preset")
    if p == "auto":
        p = "all" if (shamela_ids or author or died_after is not None or died_before is not None) else "classical"
    if p == "all": return died_before, None
    db = CLASSICAL_BEFORE if died_before is None else min(int(died_before), CLASSICAL_BEFORE)
    return db, "classical: authors who died in or before %d AH; books with no recorded death date are left out" % CLASSICAL_BEFORE


def best_window(word_tokens, slots):
    """Tightest stretch of words that holds one word from every slot. word_tokens: [(word_index, token)]. Returns (a, b) or None."""
    ev = []
    for wi, tk in word_tokens:
        for si, s in enumerate(slots):
            if tk in s: ev.append((wi, si))
    need = len(slots); have = {}; best = None; left = 0
    for right in range(len(ev)):
        have[ev[right][1]] = have.get(ev[right][1], 0) + 1
        while len(have) == need:
            a, b = ev[left][0], ev[right][0]
            if best is None or b - a < best[1] - best[0]: best = (a, b)
            sl = ev[left][1]; have[sl] -= 1
            if have[sl] == 0: del have[sl]
            left += 1
    return best


def snippet_around(text, groups, chars):
    """Cut about `chars` of text around the tightest place where the words of one phrase meet.
    Returns (snippet with the match between marks, the match, its length in words) or None."""
    words = text.split(" "); wt = []
    for wi, w in enumerate(words):
        for tk in toks(w): wt.append((wi, tk))
    best = None
    for slots in groups:
        win = best_window(wt, slots)
        if win and (best is None or win[1] - win[0] < best[1] - best[0]): best = win
    if best is None: return None
    a, b = best; match = " ".join(words[a:b + 1]); left = a; right = b; n = len(match)
    while n < chars and (left > 0 or right < len(words) - 1):
        if left > 0:
            left -= 1; n += len(words[left]) + 1
        if n < chars and right < len(words) - 1:
            right += 1; n += len(words[right]) + 1
    s = " ".join(words[left:a] + [MARK_L + match + MARK_R] + words[b + 1:right + 1])
    return s, match, b - a + 1


GROUP_N, GROUP_MIN_SHARED, GROUP_MIN_CONTAIN = 5, 15, 0.20


def group_same_words(texts):
    """Groups of near-identical texts (one passage copied from book to book). Returns lists of indexes into `texts`; the groups come
    in the order of their best-placed member. Two texts are linked when their word 5-gram shingles (over toks) share at least 15
    and shared / the smaller text's shingles >= 0.20; links are joined transitively.
    Measured in tournament round 5 (19 Nov 2026) on nearby-words results of eleven questions: 994 pages became 839 groups, and only 1 of
    104 groups of two or more put a direct page together with a page on a different matter."""
    S = []
    for t in texts:
        w = toks(t); S.append({hash(tuple(w[i:i + GROUP_N])) for i in range(len(w) - GROUP_N + 1)})
    n = len(S); parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    inv = {}
    for i, sh in enumerate(S):
        for h in sh: inv.setdefault(h, []).append(i)
    shared = {}
    for ids in inv.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)): shared[(ids[a], ids[b])] = shared.get((ids[a], ids[b]), 0) + 1
    for (i, j), c in shared.items():
        if c >= GROUP_MIN_SHARED and c / min(len(S[i]), len(S[j])) >= GROUP_MIN_CONTAIN: parent[find(i)] = find(j)
    comps = {}
    for i in range(n): comps.setdefault(find(i), []).append(i)
    return sorted(comps.values(), key=min)


NO_VECTORS = "no meaning-search for this library yet: use nearby_words"


class NoVectors(RuntimeError):
    """Raised when a search by meaning is asked of an index that has no vec256.i8 (keyword and nearby-words still work there)."""


class Searcher:
    def __init__(self, data_dir, load_model=True):
        import tantivy
        self.dir = data_dir
        self.books = json.load(open(os.path.join(data_dir, "books.json"), encoding="utf-8"))
        self.by_id = {b["book_id"]: b for b in self.books}
        self.meta = np.load(os.path.join(data_dir, "meta.npy"), mmap_mode="r")
        self.N = int(self.meta.shape[0])
        vp = os.path.join(data_dir, "vec256.i8")               # an index without this file is keyword-only (self.X is None)
        self.X = np.memmap(vp, dtype=np.int8, mode="r", shape=(self.N, DIM)) if os.path.exists(vp) else None
        self.toff = np.load(os.path.join(data_dir, "text_offsets.npy"))
        self.tfile = open(os.path.join(data_dir, "texts.bin"), "rb")
        self.tix = tantivy.Index.open(os.path.join(data_dir, "kw")); self.ks = self.tix.searcher()
        self.pool = ThreadPoolExecutor(4)
        self.model = None
        if load_model:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(MODEL, device="cpu"); self.model.max_seq_length = 512

    # ---- pieces -------------------------------------------------------------------------------------
    def embed(self, query):
        v = self.model.encode([query], normalize_embeddings=True)[0][:DIM].astype(np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def scope(self, shamela_ids=None, author=None, category=None, died_after=None, died_before=None):
        """Return the list of books that pass the filters, or None when there is no filter at all."""
        if not shamela_ids and not author and not category and died_after is None and died_before is None: return None
        sel = self.books
        if shamela_ids:
            want = {int(x) for x in shamela_ids}; sel = [b for b in sel if b["shamela_id"] in want]
        if author:
            a = norm(author).strip(); sel = [b for b in sel if a in norm(b.get("author") or "")]
        if category:
            c = norm(str(category)).strip(); sel = [b for b in sel if c == str(b.get("cat")) or c in norm(b.get("cat_name") or "")]
        if died_after is not None: sel = [b for b in sel if b.get("death") is not None and int(died_after) <= b["death"] < 9000]
        if died_before is not None: sel = [b for b in sel if b.get("death") is not None and b["death"] <= int(died_before)]
        return sel

    def _dense_chunk(self, job):
        c, d, qv, kind, k = job
        s = self.X[c:d].astype(np.float32) @ qv
        if kind is not None: s[np.asarray(self.meta[c:d, 6]) != kind] = -1e9
        kk = min(k, len(s)); idx = np.argpartition(-s, kk - 1)[:kk]
        return s[idx], idx + c

    def dense(self, qv, ranges, kind, k):
        """Exact search over the chosen rows, four chunks at a time."""
        if self.X is None: raise NoVectors(NO_VECTORS)
        if ranges is None: ranges = [[0, self.N]]
        STEP = 200000
        jobs = [(c, min(b, c + STEP), qv, kind, k) for a, b in ranges for c in range(a, b, STEP)]
        if not jobs: return []
        parts = list(self.pool.map(self._dense_chunk, jobs)) if len(jobs) > 1 else [self._dense_chunk(jobs[0])]
        best_s = np.concatenate([p[0] for p in parts]); best_i = np.concatenate([p[1] for p in parts])
        order = np.argsort(-best_s, kind="stable")[:k]
        return [int(i) for i, s in zip(best_i[order], best_s[order]) if s > -1e8]

    def keyword(self, query, book_ids, kind, k):
        tk = toks(query)
        if not tk: return []
        qs = "+(" + " ".join(tk) + ")"
        if book_ids is not None: qs = "+b:IN [" + " ".join(str(int(x)) for x in book_ids) + "] " + qs
        if kind is not None: qs = "+k:%d " % kind + qs
        hits = self.ks.search(self.tix.parse_query(qs, ["t"]), k).hits
        return [int(self.ks.doc(a)["id"][0]) for _, a in hits]

    def texts(self, ids):
        out = {}; cache = {}
        for i in ids:
            blk = i // BLOCK
            if blk not in cache:
                self.tfile.seek(int(self.toff[blk])); raw = self.tfile.read(int(self.toff[blk + 1] - self.toff[blk]))
                cache[blk] = zlib.decompress(raw).decode("utf-8").split("\n")
            out[i] = cache[blk][i % BLOCK]
        return out

    def cap_order(self, ids, cap):
        """Stop one book from filling the list: the first `cap` passages of every book come first (in their old order),
        then the next `cap` of every book, and so on. Nothing is removed."""
        if not cap or cap <= 0: return list(ids)
        seen = {}; keyed = []
        for r, i in enumerate(ids):
            b = int(self.meta[i, 0]); j = seen.get(b, 0); seen[b] = j + 1
            keyed.append((j // cap, r, i))
        keyed.sort()
        return [i for _, _, i in keyed]

    def death_of(self, i):
        d = (self.by_id.get(int(self.meta[i, 0])) or {}).get("death")
        return 99999 if d is None or d >= 9000 else int(d)

    def row(self, i):
        m = self.meta[i]; b = self.by_id.get(int(m[0])) or {}; death = b.get("death")
        return {"shamela_id": int(m[1]), "title": b.get("title"), "author": b.get("author"),
                "died_ah": None if death is None or death >= 9000 else death, "category": b.get("cat_name"),
                "part": int(m[4]), "page": int(m[5]), "shamela_page_id": int(m[3]),
                "from": "editor's footnote" if int(m[6]) == 1 else "main text"}

    def editor_guess(self, i, text):
        """True when a MAIN-TEXT passage looks like the modern editor's contents, index or bibliography page (rule from tournament round 5,
        editor_detect.py: on its 469 marked pages it flagged no real page and caught about half of the editors' pages; on a wider look on
        20 Nov about one flag in four was the first or last page of a real book. A hint, not a verdict; plain-prose introductions are missed)."""
        if not getattr(self, "flag_editor", True): return False
        m = self.meta[i]
        if int(m[6]) != 0: return False
        b = self.by_id.get(int(m[0])) or {}; n = b.get("passages") or 1; off = 0; pos = 0.5
        for a, e in b.get("ranges", []):
            if a <= i < e: pos = (off + i - a) / n; break
            off += e - a
        import editor_detect
        return bool(editor_detect.detect(text, b, int(m[4]), int(m[5]), pos)[1])

    def _editor_pages(self, ids, tx, res, hide):
        """Flag the results that look like the editor's own pages; drop them when asked. Returns how many were dropped."""
        keep = []; hidden = 0
        for i, r in zip(ids, res):
            if self.editor_guess(i, tx[i]):
                if hide: hidden += 1; continue
                r["editor_material"] = "possibly the editor's contents, index or study page: an automatic hint, check the page"
            keep.append(r)
        res[:] = keep
        return hidden

    def _scope_info(self, sel, ranges, author, applied, cap):
        info = {"books": len(self.books) if sel is None else len(sel),
                "passages": self.N if sel is None else int(sum(b - a for a, b in ranges))}
        if sel is not None and author: info["authors_matched"] = sorted({b.get("author") or "" for b in sel})[:12]
        if applied: info["preset"] = applied
        if cap: info["per_book"] = cap
        return info

    # ---- search by meaning + keywords ---------------------------------------------------------------
    def search(self, query, shamela_ids=None, author=None, category=None, died_after=None, died_before=None,
               footnotes="include", limit=8, chars=350, pool=300, mode="hybrid", qv=None, preset="auto", per_book=None, hide_editor_pages=False):
        t0 = time.time()
        if self.X is None and mode != "keyword": raise NoVectors(NO_VECTORS)
        died_before, applied = apply_preset(preset, shamela_ids, author, died_after, died_before)
        sel = self.scope(shamela_ids, author, category, died_after, died_before)
        if sel is not None and not sel:
            return {"error": "no book in the library matches these filters" +
                             (' (the classical preset is on; pass preset="all" to include modern books)' if applied else ""), "results": []}
        kind = {"include": None, "exclude": 0, "only": 1}[footnotes]
        ranges = None if sel is None else merge_ranges([r for b in sel for r in b["ranges"]])
        book_ids = None if sel is None else [b["book_id"] for b in sel]
        if qv is None and self.X is not None: qv = self.embed(query)
        t1 = time.time()
        d = self.dense(qv, ranges, kind, pool) if mode in ("hybrid", "meaning") else []
        t2 = time.time()
        kw = self.keyword(query, book_ids, kind, pool) if mode in ("hybrid", "keyword") else []
        t3 = time.time()
        sc = {}
        for lst in (d, kw):
            for r, i in enumerate(lst, 1): sc[i] = sc.get(i, 0.0) + 1.0 / (60 + r)
        fused = sorted(sc, key=lambda i: -sc[i])
        nbooks = len(self.books) if sel is None else len(sel)
        wide = not shamela_ids and not author       # measured 19 Nov 2026: the cap pushes the right page DOWN inside one author's works
        cap = int(per_book) if per_book is not None and int(per_book) >= 0 else (DEFAULT_CAP if wide and nbooks > 1 else 0)
        order = self.cap_order(fused, cap)
        top = order[:max(1, int(limit))]; tx = self.texts(top)
        dr = {i: r for r, i in enumerate(d, 1)}; kr = {i: r for r, i in enumerate(kw, 1)}
        res = []
        for i in top:
            r = self.row(i); r.update({"rank_meaning": dr.get(i), "rank_keyword": kr.get(i), "text": tx[i][:max(50, int(chars))]})
            res.append(r)
        hidden = self._editor_pages(top, tx, res, hide_editor_pages)
        return {"scope": self._scope_info(sel, ranges, author, applied, cap), "results": res, "hidden_editor_pages": hidden,
                "fused_ids": order[:pool], "uncapped_ids": fused[:pool],
                "ms": {"embed": round((t1 - t0) * 1000), "meaning": round((t2 - t1) * 1000), "keyword": round((t3 - t2) * 1000),
                       "total": round((time.time() - t0) * 1000)}}

    # ---- search for words that stand near each other ------------------------------------------------
    def near(self, phrases, window=8, shamela_ids=None, author=None, category=None, died_after=None, died_before=None,
             preset="auto", footnotes="include", limit=30, chars=350, per_book=2, sort="best", fetch=1500, group=True, hide_editor_pages=False):
        """Passages where the words of a phrase stand within `window` words of each other, in any order.
        A word may carry alternatives: "w1|w2". Several phrases are OR-ed. No meaning model is used.
        sort: "best" = pages where more of the phrases meet come first, then the stronger match (tournament round 3, 19 Nov 2026:
        576 direct pages of 994 against 483 with "oldest"); "oldest" = by the author's death year; "relevance" = match strength only."""
        t0 = time.time()
        if isinstance(phrases, str): phrases = [phrases]
        if sort not in ("best", "mixed", "oldest", "relevance"): raise KeyError("sort")
        kind = {"include": None, "exclude": 0, "only": 1}[footnotes]
        window = max(0, min(int(window), 40))
        groups = []; ignored = []
        for p in phrases or []:
            slots = []
            for w in str(p).split():
                alts = []
                for a in w.split("|"):
                    tk = toks(a)
                    if len(tk) == 1:
                        if tk[0] not in alts: alts.append(tk[0])
                    elif a.strip(): ignored.append(a)
                if alts: slots.append(alts)
            if len(slots) >= 2: groups.append(slots)
            elif str(p).strip(): ignored.append(str(p))
        if not groups:
            return {"error": "give at least one phrase of two or more Arabic words (words of one letter are ignored)", "results": []}
        died_before, applied = apply_preset(preset, shamela_ids, author, died_after, died_before)
        sel = self.scope(shamela_ids, author, category, died_after, died_before)
        if sel is not None and not sel:
            return {"error": "no book in the library matches these filters" +
                             (' (the classical preset is on; pass preset="all" to include modern books)' if applied else ""), "results": []}
        ranges = None if sel is None else merge_ranges([r for b in sel for r in b["ranges"]])
        filt = ""
        if kind is not None: filt += "+k:%d " % kind
        if sel is not None: filt += "+b:IN [" + " ".join(str(int(b["book_id"])) for b in sel) + "] "
        agg = {}; total = 0; cut = False; used = 0
        for slots in groups:
            parts = []
            for combo in itertools.product(*slots):
                parts.append('t:"%s"~%d' % (" ".join(combo), window))
                if combo[::-1] != combo: parts.append('t:"%s"~%d' % (" ".join(combo[::-1]), window))
            if len(parts) > 400:
                ignored.append("a phrase with too many word combinations (%d, the limit is 400)" % len(parts)); continue
            used += 1
            r = self.ks.search(self.tix.parse_query(filt + "+(" + " ".join(parts) + ")", ["t"]), max(1, int(fetch)))
            cnt = int(getattr(r, "count", None) or len(r.hits)); total += cnt; cut = cut or cnt > len(r.hits); seen = set()
            for score, addr in r.hits:                      # one page counts once per phrase
                i = int(self.ks.doc(addr)["id"][0]); m = self.meta[i]; k = (int(m[0]), int(m[2]), int(m[6]))
                if k in seen: continue
                seen.add(k); e = agg.get(k)
                if e is None: agg[k] = [1, float(score), i]
                else:
                    e[0] += 1
                    if score > e[1]: e[1] = float(score)
        if not used:
            return {"error": "every phrase had too many word combinations: use fewer alternatives per word", "results": []}
        t1 = time.time()
        items = list(agg.values())                          # [phrases that meet on the page, best match score, passage id]
        mixed = sort == "mixed"
        if sort in ("best", "mixed"): items.sort(key=lambda x: (-x[0], -x[1]))
        elif sort == "relevance": items.sort(key=lambda x: -x[1])
        else: items.sort(key=lambda x: (self.death_of(x[2]), int(self.meta[x[2], 0]), x[2]))
        ids = [x[2] for x in items]; met = {x[2]: x[0] for x in items}
        per = {}
        for i in ids:
            b = int(self.meta[i, 0]); e = per.get(b)
            if e is None: per[b] = [1, i]
            else:
                e[0] += 1
                if i < e[1]: e[1] = i
        blist = sorted(per.items(), key=lambda kv: (self.death_of(kv[1][1]), kv[0]))
        by_book = []
        for b, (n, i) in blist[:80]:
            x = self.row(i)
            by_book.append({"shamela_id": x["shamela_id"], "title": x["title"], "author": x["author"], "died_ah": x["died_ah"],
                            "hits": n, "first_at": "%d/%d" % (x["part"], x["page"])})
        cap = max(0, int(per_book or 0))
        order = self.cap_order(ids, cap)
        if mixed:                                           # every fifth place goes to the oldest author not yet shown, one page a book from that side
            old_first = sorted(ids, key=lambda i: (self.death_of(i), int(self.meta[i, 0]), i)); out = []; seen = set(); used = set(); bi = oi = 0
            want = min(len(order), max(1, int(limit)))
            while len(out) < want:
                pick = None
                if (len(out) + 1) % 5 == 0:
                    while oi < len(old_first) and (old_first[oi] in seen or int(self.meta[old_first[oi], 0]) in used): oi += 1
                    if oi < len(old_first): pick = old_first[oi]; used.add(int(self.meta[pick, 0]))
                if pick is None:
                    while bi < len(order) and order[bi] in seen: bi += 1
                    if bi >= len(order): break
                    pick = order[bi]
                out.append(pick); seen.add(pick)
            order = out
        top = order[:max(1, int(limit))]; tx = self.texts(top)
        gsets = [[set(s) for s in slots] for slots in groups]
        res = []
        for i in top:
            x = self.row(i); sn = snippet_around(tx[i], gsets, max(50, int(chars)))
            if sn: x.update({"phrases_met": met[i], "match": sn[1], "match_words": sn[2], "text": sn[0]})
            else: x.update({"phrases_met": met[i], "match": None, "text": tx[i][:max(50, int(chars))]})
            res.append(x)
        hidden = self._editor_pages(top, tx, res, hide_editor_pages)
        if hidden: top = [i for i in top if not self.editor_guess(i, tx[i])]
        grouped = None
        if group and len(res) > 1:                          # one passage copied from book to book is shown once, under its earliest author
            gs = group_same_words([tx[i] for i in top]); merged = []
            for g in gs:
                g = sorted(g, key=lambda j: (self.death_of(top[j]), j)); head = res[g[0]]
                if len(g) > 1:
                    head["same_words_in"] = [{k: res[j].get(k) for k in ("shamela_id", "title", "author", "died_ah", "part", "page", "shamela_page_id", "from", "phrases_met")}
                                             for j in g[1:]]
                    head["phrases_met"] = max(res[j]["phrases_met"] for j in g)
                merged.append(head)
            grouped = {"pages": len(res), "items": len(merged)}; res = merged
        out = {"scope": self._scope_info(sel, ranges, author, applied, cap), "sort": sort, "total_hits": total, "pages_with_hits": len(ids),
               "books_with_hits": len(per), "by_book": by_book, "results": res, "hidden_editor_pages": hidden,
               "ms": {"index": round((t1 - t0) * 1000), "total": round((time.time() - t0) * 1000)}}
        if grouped and grouped["items"] < grouped["pages"]:
            out["grouped"] = dict(grouped, note="pages with the same words are shown once, under the earliest author, with the others in same_words_in; "
                                                "that is the earliest book holding these words here, not proof of who copied whom")
        if cut: out["note"] = "at least one phrase had more hits than were read (%d per phrase); narrow the scope or the phrase to see all" % int(fetch)
        if len(per) > len(by_book): out["note_books"] = "by_book lists the first 80 of %d books" % len(per)
        if ignored: out["ignored"] = ignored[:20]
        return out

    # ---- several wordings of one question -----------------------------------------------------------
    def search_multi(self, queries, limit=8, chars=350, **kw):
        """Each wording is searched as usual; the result lists are fused by rank (tournament round 3, 19 Nov 2026: direct pages in the
        first ten over ten questions: 171 with the first wording alone, 202 with the second alone, 204 fused)."""
        t0 = time.time(); qs = [str(q) for q in queries if q and str(q).strip()][:5]
        if not qs: return {"error": "empty query", "results": []}
        if len(qs) == 1: return self.search(qs[0], limit=limit, chars=chars, **kw)
        sc = {}; ranks = {}; first = None
        for n, q in enumerate(qs):
            r = self.search(q, limit=1, chars=50, **kw)
            if r.get("error"): return r
            if first is None: first = r
            for rank, i in enumerate(r["fused_ids"][:60], 1):
                sc[i] = sc.get(i, 0.0) + 1.0 / (60 + rank); ranks.setdefault(i, [None] * len(qs))[n] = rank
        cap = (first.get("scope") or {}).get("per_book", 0)
        order = self.cap_order(sorted(sc, key=lambda i: -sc[i]), cap)
        top = order[:max(1, int(limit))]; tx = self.texts(top); res = []
        for i in top:
            x = self.row(i); x.update({"rank_in_each_wording": ranks[i], "text": tx[i][:max(50, int(chars))]}); res.append(x)
        hidden = self._editor_pages(top, tx, res, bool(kw.get("hide_editor_pages")))
        info = dict(first.get("scope") or {}); info["wordings"] = len(qs)
        return {"scope": info, "results": res, "hidden_editor_pages": hidden, "fused_ids": order[:300], "ms": {"total": round((time.time() - t0) * 1000)}}
