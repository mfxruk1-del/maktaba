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


class Searcher:
    def __init__(self, data_dir, load_model=True):
        import tantivy
        self.dir = data_dir
        self.books = json.load(open(os.path.join(data_dir, "books.json"), encoding="utf-8"))
        self.by_id = {b["book_id"]: b for b in self.books}
        self.meta = np.load(os.path.join(data_dir, "meta.npy"), mmap_mode="r")
        self.N = int(self.meta.shape[0])
        self.X = np.memmap(os.path.join(data_dir, "vec256.i8"), dtype=np.int8, mode="r", shape=(self.N, DIM))
        self.toff = np.load(os.path.join(data_dir, "text_offsets.npy"))
        self.tfile = open(os.path.join(data_dir, "texts.bin"), "rb")
        self.tix = tantivy.Index.open(os.path.join(data_dir, "kw")); self.ks = self.tix.searcher()
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

    def dense(self, qv, ranges, kind, k):
        if ranges is None: ranges = [[0, self.N]]
        best_s = np.empty(0, np.float32); best_i = np.empty(0, np.int64); STEP = 400000
        for a, b in ranges:
            for c in range(a, b, STEP):
                d = min(b, c + STEP)
                s = self.X[c:d].astype(np.float32) @ qv
                if kind is not None: s[np.asarray(self.meta[c:d, 6]) != kind] = -1e9
                kk = min(k, len(s)); idx = np.argpartition(-s, kk - 1)[:kk]
                best_s = np.concatenate([best_s, s[idx]]); best_i = np.concatenate([best_i, idx + c])
                if len(best_s) > 4 * k:
                    keep = np.argpartition(-best_s, k - 1)[:k]; best_s = best_s[keep]; best_i = best_i[keep]
        order = np.argsort(-best_s)[:k]
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

    # ---- the search ---------------------------------------------------------------------------------
    def search(self, query, shamela_ids=None, author=None, category=None, died_after=None, died_before=None,
               footnotes="include", limit=8, chars=350, pool=300, mode="hybrid", qv=None):
        t0 = time.time()
        sel = self.scope(shamela_ids, author, category, died_after, died_before)
        if sel is not None and not sel: return {"error": "no book in the library matches these filters", "results": []}
        kind = {"include": None, "exclude": 0, "only": 1}[footnotes]
        ranges = None if sel is None else merge_ranges([r for b in sel for r in b["ranges"]])
        book_ids = None if sel is None else [b["book_id"] for b in sel]
        if qv is None: qv = self.embed(query)
        t1 = time.time()
        d = self.dense(qv, ranges, kind, pool) if mode in ("hybrid", "meaning") else []
        t2 = time.time()
        kw = self.keyword(query, book_ids, kind, pool) if mode in ("hybrid", "keyword") else []
        t3 = time.time()
        sc = {}
        for lst in (d, kw):
            for r, i in enumerate(lst, 1): sc[i] = sc.get(i, 0.0) + 1.0 / (60 + r)
        fused = sorted(sc, key=lambda i: -sc[i])
        top = fused[:max(1, int(limit))]; tx = self.texts(top)
        dr = {i: r for r, i in enumerate(d, 1)}; kr = {i: r for r, i in enumerate(kw, 1)}
        res = []
        for i in top:
            m = self.meta[i]; b = self.by_id.get(int(m[0])) or {}
            death = b.get("death")
            res.append({"shamela_id": int(m[1]), "title": b.get("title"), "author": b.get("author"),
                        "died_ah": None if death is None or death >= 9000 else death, "category": b.get("cat_name"),
                        "part": int(m[4]), "page": int(m[5]), "shamela_page_id": int(m[3]),
                        "from": "editor's footnote" if int(m[6]) == 1 else "main text",
                        "rank_meaning": dr.get(i), "rank_keyword": kr.get(i), "text": tx[i][:max(50, int(chars))]})
        info = {"books": self.books.__len__() if sel is None else len(sel),
                "passages": self.N if sel is None else int(sum(b - a for a, b in ranges))}
        if sel is not None and author: info["authors_matched"] = sorted({b.get("author") or "" for b in sel})[:12]
        return {"scope": info, "results": res, "fused_ids": fused[:pool],
                "ms": {"embed": round((t1 - t0) * 1000), "meaning": round((t2 - t1) * 1000), "keyword": round((t3 - t2) * 1000),
                       "total": round((time.time() - t0) * 1000)}}
