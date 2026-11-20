# -*- coding: utf-8 -*-
"""T1. Which 'done' Kutub works does Shamela already have?   ~/semsearch/venv/bin/python ~/kutub/catalog.py
Writes ~/kutub/catalog.json (one record per done book) and ~/kutub/catalog_check.txt (40 matched pairs + 40 unmatched, random).

RULE (conservative: a miss costs little, a false match hides a book):
  the two titles are EQUAL after normalising (semcore.norm; a leading "كتاب" off; an edition tail after " - " or " ط " / " ت " off;
  punctuation off; a Shamela title "A = B" counts as two titles)   AND
     (a) both death years are known and differ by at most 5                                   -> rule "title+year"
  or (b) a year is missing on one side or both, and the title has at least 3 words            -> rule "title3+noyear"
  One extra safeguard on top of the brief's rule (it can only REFUSE a pair, never add one). The Latin author name from Kutub and the
  Arabic one from Shamela are reduced to consonant skeletons (skel_lat / skel_ar) and compared part by part:
     in (a) a pair whose two author names are both readable and share no part is refused (measured on the first run: 19 such pairs in
            5,500, two of them plainly different works with one title, e.g. "حكم تارك الصلاة" by Ibn Uthaymin against al-Albani's);
            Kept all the same when the two years are EXACTLY equal, not after 1300, and the title has 3 words or more (rule "title+same
            year, classical": one scholar under two names, e.g. "Ibn al-Mayyit" / "البديري"; every such pair read on 20 Nov 2026 was one work);
     in (b) one shared name part is REQUIRED, because there is no year to lean on.
  "maybe_shamela_id" is information only (in_shamela stays false): a Shamela title that begins with this title or the other way round,
  same author part, years not in conflict. Such a book is probably in Shamela under a longer or shorter title.
Open the Kutub file read-only and immutable, never written."""
import sys, os, re, json, random, sqlite3, unicodedata, collections
HERE = os.path.dirname(os.path.abspath(__file__))
SEM_HOME = os.environ.get("SEM_HOME", os.path.join(os.path.expanduser("~"), "semsearch"))        # where semcore.py and data/books.json (Shamela's list) live
sys.path.insert(0, SEM_HOME)
import semcore

KUTUB = "file:%s?mode=ro&immutable=1" % os.environ.get("KUTUB_DB", os.path.join(HERE, "index.sqlite3"))
SHAMELA = os.path.join(SEM_HOME, "data", "books.json")
NOT_AR = re.compile("[^ء-ي0-9٠-٩ ]+")
DASH = re.compile(r"\s+[-–—]\s+"); EDITION = re.compile(r"^(?:ط|ت|طبعه|تحقيق)\s+\S"); ED_TAIL = re.compile(r"\s+(?:ط|ت)\s+\S.*$")
NOW_AH = 1448          # Kutub writes 1450 for living authors: a year after today is "no year"


def tnorm(t):
    """Normalised words of a title piece: semcore.norm, punctuation off, a leading كتاب off."""
    t = semcore.norm((t or "").replace("ﷺ", " صلى الله عليه وسلم ")).strip()
    t = re.sub(r"\s+", " ", NOT_AR.sub(" ", t)).strip()
    if t.startswith("كتاب ") and len(t.split()) > 2: t = t[5:]
    return t


def forms(title):
    """[(base, other tails)] for a catalogue title. The base is the title before " - ..." and before an edition tail (" ط ..." / " ت ...").
    Tails after " - " that name an EDITION (ط / ت ...) are dropped; any other tail (a part of a series, a transmission, an author's
    name) is kept apart: two titles that BOTH carry such tails must carry the same ones. "A = B" also gives A and B on their own."""
    out = []
    for v in [title or ""] + ([x for x in (title or "").split("=")] if "=" in (title or "") else []):
        segs = DASH.split(semcore.norm(v).strip()); base = tnorm(ED_TAIL.sub("", segs[0]))
        other = frozenset(x for x in (tnorm(ED_TAIL.sub("", g)) for g in segs[1:] if not EDITION.match(g.strip())) if x)
        if base and (base, other) not in out: out.append((base, other))
    return out


# ---- author names: Latin transliteration (Kutub) against Arabic (Shamela), as consonant skeletons ----------------------------
AR2LAT = {"ب": "b", "ت": "t", "ث": "t", "ج": "j", "ح": "h", "خ": "k", "د": "d", "ذ": "d", "ر": "r", "ز": "z", "س": "s", "ش": "s", "ص": "s", "ض": "d",
          "ط": "t", "ظ": "z", "غ": "g", "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h"}        # ع ء ا و ي and vowels are dropped
STOP = {"bn", "bd", "mhmd", "hmd", "dn", "mm", "hfz", "qd", "hsn", "mr", "bnt"}      # ibn, abd, Muhammad/Mahmud, Ahmad/Hamid, al-Din, imam, hafiz, qadi, Hasan/Husayn, Umar


DROP = {"bn", "b", ""}                       # ibn / b. / bin / abu: written too many ways to compare


def seq_ar(name):
    """Every part of an Arabic name as a consonant skeleton, in order."""
    out = []
    for w in re.findall("[ء-ي]+", semcore.norm(re.sub(r"\(.*?\)", " ", name or ""))):
        if w.startswith("ال") and len(w) > 3: w = w[2:]
        if w.endswith("ه") and len(w) >= 2: w = w[:-1]                # ta marbuta / final ha: Latin writes "a" or drops it
        s = "".join(AR2LAT.get(c, "") for c in w)
        if s not in DROP: out.append(s)
    return out


def seq_lat(name):
    """The same for a transliterated name (or a slug with the hyphens turned into spaces)."""
    t = unicodedata.normalize("NFD", (name or "").lower()).replace("h\u0323", "7")          # ḥ (ح) is kept apart from a plain h
    t = "".join(c for c in t if not unicodedata.combining(c))
    for ch in "ʿʾ'’‘`": t = t.replace(ch, "")
    out = []
    for w in re.findall("[a-z7]+", re.sub(r"\b(al|el|as|ad|ar|az|an|at|ash)-", " ", t).replace("-", " ")):
        w = re.sub(r"(.)\1+", r"\1", w)
        w = w.replace("th", "t").replace("kh", "k").replace("dh", "d").replace("sh", "s").replace("gh", "g"); w = re.sub(r"(.)\1+", r"\1", w)
        if w.endswith("h") and len(w) > 2: w = w[:-1]                 # a final ha / ta marbuta, dropped on the Arabic side too
        s = re.sub("[aeiouwyc]", "", w.replace("7", "h"))
        if s not in DROP: out.append(s)
    return out


def skel_ar(name): return {x for x in seq_ar(name) if len(x) >= 2 and x not in STOP}


def skel_lat(name): return {x for x in seq_lat(name) if len(x) >= 2 and x not in STOP}


def shared(a, b):
    """One distinctive name part in common: equal, or (four consonants or more) one inside the other ("Ṭāshkubrīzāda" / "طاشكبري زاده")."""
    if a & b: return True
    return any(len(x) >= 4 and len(y) >= 4 and (x in y or y in x) for x in a for y in b)


def same_author(latin, slug, arabic):
    """(both names readable, they agree). They agree on one distinctive part in common, or when the whole names are the same parts in
    the same order (for names made only of common parts: "Muḥammad Ḥassān" / "محمد حسان")."""
    sl = seq_lat(latin); sa = seq_ar(arabic); la = skel_lat(latin) | skel_lat((slug or "").replace("-", " ")); aa = skel_ar(arabic)
    return bool(sl) and bool(sa), shared(la, aa) or (bool(sl) and sl == sa)


def year_of(v):
    try: v = int(v)
    except Exception: return None
    return v if 0 < v <= NOW_AH else None


def main():
    random.seed(20261120)
    sh = json.load(open(SHAMELA, encoding="utf-8")); by_key = collections.defaultdict(list)
    for b in sh:
        for k, other in forms(b.get("title") or ""): by_key[k].append((b, other))
    con = sqlite3.connect(KUTUB, uri=True)
    rows = con.execute("SELECT slug, title, title_arabic, author, author_slug, year, pages_done, chars FROM books WHERE status='done' ORDER BY slug").fetchall()
    out = []; rules = collections.Counter(); pairs = []; refused = []; maybe = []
    ALLKEYS = [(k, b) for k, bs in by_key.items() for b, _ in bs]
    for slug, title, tar, author, aslug, year, pages, chars in rows:
        rec = {"slug": slug, "title_arabic": tar, "title": title, "author": author, "author_slug": aslug, "year": year, "pages_done": pages, "chars": chars,
               "in_shamela": False, "shamela_id": None, "rule": "no arabic title" if not (tar or "").strip() else "no equal title"}
        ky = year_of(year); la = skel_lat(author) | skel_lat((aslug or "").replace("-", " "))
        best = None
        for k, other in forms(tar or ""):
            words = len(k.split())
            for b, bother in by_key.get(k, []):
                sy = year_of(b.get("death")); both, same = same_author(author, aslug, b.get("author"))
                if other and bother and other != bother: rule = "refused:another part or version (tails differ)"
                elif ky is not None and sy is not None:
                    if abs(ky - sy) > 5: rule = "refused:year"
                    elif both and not same: rule = "title+same year, classical" if (ky == sy and ky <= 1300 and words >= 3) else "refused:author"
                    else: rule = "title+year"
                else:
                    if words < 3: rule = "refused:short title, no year"
                    elif not same: rule = "refused:author"            # no year to lean on: one shared name part is required
                    else: rule = "title3+noyear"
                cand = (0 if not rule.startswith("refused") else 1, rule, b)
                if best is None or cand[0] < best[0]: best = cand
        if best is not None:
            rec["rule"] = best[1]
            if best[0] == 0:
                b = best[2]; rec["in_shamela"] = True; rec["shamela_id"] = b["shamela_id"]
                pairs.append((rec, b))
            else: refused.append((rec, best[2]))
        if not rec["in_shamela"] and (tar or "").strip():
            k = forms(tar)[0][0] if forms(tar) else ""
            if len(k.split()) >= 2:
                for k2, b in ALLKEYS:
                    if k2 == k or not (k2.startswith(k + " ") or (k.startswith(k2 + " ") and len(k2.split()) >= 2)): continue
                    sy = year_of(b.get("death"))
                    if ky is not None and sy is not None and abs(ky - sy) > 5: continue
                    if not shared(la, skel_ar(b.get("author"))): continue
                    rec["maybe_shamela_id"] = b["shamela_id"]; maybe.append((rec, b)); break
        rules[rec["rule"]] += 1; out.append(rec)
    json.dump(out, open(os.path.join(HERE, "catalog.json"), "w", encoding="utf-8"), ensure_ascii=False)
    yes = [r for r in out if r["in_shamela"]]; no = [r for r in out if not r["in_shamela"]]
    print("done books", len(out), "| matched to Shamela", len(yes), "| left for the index", len(no))
    print("pages: matched", sum(r["pages_done"] or 0 for r in yes), "| left", sum(r["pages_done"] or 0 for r in no))
    print("characters: matched", sum(r["chars"] or 0 for r in yes), "| left", sum(r["chars"] or 0 for r in no))
    print("distinct Shamela books matched", len({r["shamela_id"] for r in yes}))
    for k, v in rules.most_common(): print("  rule %-32s %d" % (k, v))
    print("left for the index but probably in Shamela under a longer/shorter title (maybe_shamela_id, information only):", len(maybe),
          "| their characters", sum(r["chars"] or 0 for r, _ in maybe))
    with open(os.path.join(HERE, "catalog_check.txt"), "w", encoding="utf-8") as f:
        f.write("CATALOG SPOT CHECK (random, seed 20261120). done %d | matched %d | left for the index %d\n\n" % (len(out), len(yes), len(no)))
        f.write("== 40 MATCHED PAIRS (Kutub  <->  Shamela) ==\n")
        for rec, b in random.sample(pairs, min(40, len(pairs))):
            f.write("[%s] K: %s | %s | d.%s | %s pages\n      S: %s | %s | d.%s | shamela_id %d\n" % (rec["rule"], rec["title_arabic"], rec["author"], rec["year"], rec["pages_done"],
                    b["title"], b["author"], year_of(b["death"]), b["shamela_id"]))
        f.write("\n== 40 UNMATCHED (go into the Kutub index) ==\n")
        for rec in random.sample(no, min(40, len(no))):
            f.write("[%s] %s | %s | d.%s | %s pages | %s\n" % (rec["rule"], rec["title_arabic"] or rec["title"], rec["author"], rec["year"], rec["pages_done"], rec["slug"]))
        f.write("\n== 30 'MAYBE' (NOT matched, in the Kutub index; a Shamela title begins the same way, same author) ==\n")
        for rec, b in random.sample(maybe, min(30, len(maybe))):
            f.write("K: %s | %s | d.%s\n      S: %s | %s | d.%s | shamela_id %d\n" % (rec["title_arabic"], rec["author"], rec["year"], b["title"], b["author"],
                    year_of(b["death"]), b["shamela_id"]))
        f.write("\n== 30 REFUSED though the title was equal (they stay in the Kutub index) ==\n")
        for rec, b in random.sample(refused, min(30, len(refused))):
            f.write("[%s] K: %s | %s | d.%s\n      S: %s | %s | d.%s | shamela_id %d\n" % (rec["rule"], rec["title_arabic"], rec["author"], rec["year"], b["title"], b["author"],
                    year_of(b["death"]), b["shamela_id"]))


if __name__ == "__main__":
    main()
