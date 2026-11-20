# -*- coding: utf-8 -*-
"""How much of the Kutub index is text that Shamela already holds? Measured by CONTENT, not by title (catalog.py matches titles only).
   ~/semsearch/venv/bin/python ~/kutub/overlap_check.py [sample size]      -> overlap_check.json beside this file + a summary
For every book of the Kutub index (SEM_HOME/data_kutub): five passages (at 20, 35, 50, 65, 80 % of the book), from the middle of each an
unbroken run of 8 index words (semcore.toks), searched as an exact phrase in the Shamela keyword index (SEM_HOME/data/kw, read only).
The Shamela book that most probes land in is the candidate twin. Verdict "same work in Shamela": at least 3 of 5 probes (2 of 2-3,
3 of 4) in ONE Shamela book whose size is 0.4 to 2.5 times this book's. kt_build.py --skip-twins leaves those books out of the index.
Not judged by a reader: an abridgement that copies its source word for word, or a text printed inside its commentary, can look like a twin.

overlap_check.json is THE RECORD OF WHAT WAS LEFT OUT. A later run on an index that no longer holds the twins keeps their old records
(a book that is not in the index today is never dropped from the file), so a rebuild with --skip-twins keeps leaving them out.
Run of 20 Nov 2026 on the full index (4,726 books): 1,975 same work, 1,438 not found, 996 some shared text only, 298 inside a Shamela
book of another size, 19 too short to judge.
Paths: SEM_HOME (default ~/semsearch) in the environment; SEM_CODE = another folder to take semcore.py from."""
import os, sys, json, random, time, collections
HERE = os.path.dirname(os.path.abspath(__file__))
SEM_HOME = os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch"))
sys.path.insert(0, os.environ.get("SEM_CODE") or SEM_HOME)
import semcore

OUT = os.path.join(HERE, "overlap_check.json"); SAME = "same work in Shamela"


def verdict(r):
    if r["probes"] < 2: return "too short to judge"
    if r["probes_found"] >= max(2, (r["probes"] * 3 + 4) // 5):
        ratio = r["shamela_passages"] / max(1, r["passages"])
        return SAME if 0.4 <= ratio <= 2.5 else "its text stands inside a Shamela book of another size"
    if r["probes_found"] >= 1: return "some shared text only"
    return "not found in Shamela"


def main():
    K = semcore.Searcher(os.path.join(SEM_HOME, "data_kutub"), load_model=False); S = semcore.Searcher(os.path.join(SEM_HOME, "data"), load_model=False)
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    books = K.books if not sample else random.Random(11).sample(K.books, sample)
    out = []; t0 = time.time()
    for n, b in enumerate(books, 1):
        a, e = b["ranges"][0]; npass = e - a
        ids = sorted({a + int(npass * f) for f in (0.2, 0.35, 0.5, 0.65, 0.8)})[:5] if npass >= 5 else list(range(a, e))
        tx = K.texts(ids); votes = collections.Counter(); probes = 0
        for i in ids:
            tk = semcore.toks(tx[i])
            if len(tk) < 24: continue
            run = tk[len(tk) // 2 - 4: len(tk) // 2 + 4]; probes += 1
            try: hits = S.ks.search(S.tix.parse_query('t:"%s"' % " ".join(run), ["t"]), 40).hits
            except Exception: continue
            for sb in {int(S.meta[int(S.ks.doc(ad)["id"][0]), 0]) for _, ad in hits}: votes[sb] += 1
        best = votes.most_common(1)[0] if votes else (None, 0); sbk = S.by_id.get(best[0]) if best[0] is not None else None
        r = {"slug": b["kutub_slug"], "title": b["title"], "passages": npass, "probes": probes, "probes_found": best[1],
             "shamela_id": sbk["shamela_id"] if sbk else None, "shamela_title": sbk["title"] if sbk else None, "shamela_passages": sbk["passages"] if sbk else None,
             "maybe_shamela_id": b.get("maybe_shamela_id")}
        r["verdict"] = verdict(r); out.append(r)
        if n % 500 == 0: print(n, "books,", round(time.time() - t0), "s", flush=True)
    c = collections.Counter(r["verdict"] for r in out); pc = collections.Counter()
    for r in out: pc[r["verdict"]] += r["passages"]
    tot = max(1, sum(pc.values()))
    for k, v in c.most_common(): print("%5d books | %8d passages (%4.1f%%) | %s" % (v, pc[k], 100 * pc[k] / tot, k))
    if sample: print("a sample: nothing was written"); return
    kept = 0
    if os.path.exists(OUT):                                  # the books left out of today's index keep their old records
        now = {r["slug"] for r in out}; old = [r for r in json.load(open(OUT, encoding="utf-8")) if r["slug"] not in now]; kept = len(old); out += old
    json.dump(out, open(OUT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False); os.replace(OUT + ".tmp", OUT)
    print("written: %s (%d records; %d kept from the earlier file for books that are not in the index now)" % (OUT, len(out), kept))


if __name__ == "__main__":
    main()
