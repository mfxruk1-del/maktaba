# -*- coding: utf-8 -*-
"""Put the imported books (kept by ~/kutub/sort_decide.py; texts in texts_extra.db) into the ONE catalogue: books.json and the books table of library.db,
each under its work, on a shelf. Also writes categories.json (groups, shelves, descriptions) and shamela_refs.json (the Shamela editions of the same works).
   ~/semsearch/venv/bin/python ~/library/register_extra.py          (safe to run again: imported rows are replaced; the owner's own 38 books are only given a shelf)
Backup made once: books.json.bak-before-merge (library.db is made from books.json by maktaba/build_index.py)."""
import os, re, sys, json, shutil, sqlite3
import numpy as np
HOME = os.path.expanduser("~"); LIB = os.path.join(HOME, "library"); SEM = os.path.join(HOME, "semsearch"); sys.path.insert(0, SEM)
if not os.path.exists(os.path.join(LIB, "books.json.bak-before-merge")): shutil.copy2(os.path.join(LIB, "books.json"), os.path.join(LIB, "books.json.bak-before-merge"))

G = [  # group (Arabic, English), then shelves: (name, what is on it)
 ("القرآن وعلومه", "Qur'an and its sciences", [("التفسير", "Commentaries on the Qur'an, verse by verse."), ("علوم القرآن وأصول التفسير", "The sciences of the Qur'an: abrogation, occasions of revelation, rules of commentary."),
   ("التجويد والقراءات", "Recitation and the canonical readings.")]),
 ("الحديث وعلومه", "Hadith and its sciences", [("كتب السنة", "Collections of hadith with their chains: sunan, musnads, small parts (ajza')."), ("شروح الحديث", "Commentaries on the hadith collections."),
   ("التخريج والأطراف", "Tracing reports to their sources (takhrij) and indexes of their openings."), ("العلل والسؤلات الحديثية", "Hidden defects in reports, and the critics' answers to their students."),
   ("علوم الحديث", "The terminology and method of hadith criticism."), ("الجوامع", "Large gathered collections drawn from many books.")]),
 ("العقيدة", "Creed", [("العقيدة", "Creed and theology."), ("الفرق والردود", "The sects and the refutations written against them.")]),
 ("الفقه وأصوله", "Law and legal theory", [("الفقه الحنفي", "Hanafi law: texts, commentaries, glosses and fatwa collections."), ("الفقه المالكي", "Maliki law."), ("الفقه الشافعي", "Shafi'i law."),
   ("الفقه الحنبلي", "Hanbali law."), ("الفقه العام", "Comparative law across the schools."), ("مسائل فقهية", "Treatises on single legal questions."), ("الفتاوى", "Collections of fatwas."),
   ("أصول الفقه", "Legal theory: how rulings are drawn from the sources."), ("علوم الفقه والقواعد الفقهية", "Legal maxims and the auxiliary sciences of law."),
   ("السياسة الشرعية والقضاء", "Governance, judgeship and public law."), ("الفرائض والوصايا", "Inheritance shares and bequests.")]),
 ("التزكية والسيرة", "Spirituality and the Prophet's life", [("الرقائق والآداب والأذكار", "Purification of the heart, manners, remembrance; the works of tasawwuf sit here."), ("السيرة النبوية", "The life, qualities and battles of the Prophet ﷺ.")]),
 ("التاريخ والتراجم", "History and biography", [("التاريخ", "Chronicles and histories."), ("التراجم والطبقات", "Biographical dictionaries and generations of scholars."), ("مناقب أبي حنيفة", "The virtues and defence of Imam Abu Hanifa."),
   ("الأنساب", "Genealogy."), ("البلدان والرحلات", "Lands, cities and travel accounts.")]),
 ("اللغة والأدب", "Language and literature", [("كتب اللغة", "Works on the Arabic language."), ("الغريب والمعاجم", "Dictionaries and rare words."), ("النحو والصرف", "Grammar and morphology."), ("البلاغة", "Rhetoric."),
   ("الأدب", "Literature and anthologies."), ("الشعر ودواوينه", "Poetry and collected poems."), ("العروض والقوافي", "Metre and rhyme.")]),
 ("علوم أخرى", "Other sciences", [("المنطق", "Logic."), ("الطب", "Medicine."), ("فهارس الكتب والأدلة", "Catalogues and bibliographies."), ("كتب عامة", "General works."), ("علوم أخرى", "Other sciences."), ("غير مصنف", "Not yet placed on a shelf.")]),
]
json.dump([{"ar": a, "en": e, "shelves": [{"ar": s, "en": d} for s, d in sh]} for a, e, sh in G], open(os.path.join(LIB, "categories.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
SHELVES = {s for _, _, sh in G for s, _ in sh}
OWN = {"الفقه الحنفي": "bazzaziyya dhakhira muhit-radawi multaqat tatarkhaniyya radd-muhtar jadd-mumtar fatawa-ridawiyya", "مناقب أبي حنيفة": "dinawari fadail kardari kashf khayrat makki tabyid uqud zaranjari tanib",
       "كتب عامة": "maqalat", "علوم الفقه والقواعد الفقهية": "fiqh-iraq"}
OWN = {w: s for s, ws in OWN.items() for w in ws.split()}
srt = [d for d in json.load(open(os.path.join(HOME, "kutub", "sorted.json"), encoding="utf-8")) if d.get("keep")]
ar = {}
for folder in ("data_maktaba", "data_kutub"):                # the authors' Arabic names: in the one index since the merge, before it in the index of the imported books
    p = os.path.join(SEM, folder, "books.json")
    if not ar and os.path.exists(p): ar = {b["kutub_slug"]: b.get("author_ar") for b in json.load(open(p, encoding="utf-8")) if b.get("kutub_slug")}
if not ar: sys.exit("no search index holds the imported books (data_maktaba, data_kutub): the authors' Arabic names are read from it")
strip = lambda t: re.sub(r"\s*[-–]\s*(ط|ت)\s.*$", "", t or "").strip()

con = sqlite3.connect(os.path.join(LIB, "library.db")); con.row_factory = sqlite3.Row
have = {r[1] for r in con.execute("PRAGMA table_info(books)")}
for col, typ in (("shelf", "TEXT"), ("died", "INTEGER"), ("store", "TEXT"), ("author_latin", "TEXT"), ("shamela_id", "INTEGER"), ("relation", "TEXT"), ("new_share", "REAL"), ("note", "TEXT"), ("chars", "INTEGER")):
    if col not in have: con.execute("ALTER TABLE books ADD COLUMN %s %s" % (col, typ))
own_ids = {r["id"] for r in con.execute("SELECT id FROM books WHERE store IS NULL OR store != 'extra'")}; own_works = {r["work"] for r in con.execute("SELECT work FROM books WHERE store IS NULL OR store != 'extra'")}
for r in con.execute("SELECT id, work, author FROM books WHERE store IS NULL OR store != 'extra'").fetchall():
    m = re.search(r"ت\s*(\d{3,4})", r["author"] or ""); con.execute("UPDATE books SET shelf=?, died=?, store='own' WHERE id=?", (OWN.get(r["work"], "غير مصنف"), int(m.group(1)) if m else None, r["id"]))
con.execute("DELETE FROM books WHERE store='extra'")
SOURCE = ("Imported on 20 Nov 2026 from the extra corpus. Mostly machine-read text; the editors' notes are not split from the author's words and there are no chapter headings. "
          "page = running page number (from 0); printed_page = volume/page when known. Check the wording before quoting.")
x = sqlite3.connect("file:%s?mode=ro" % os.path.join(LIB, "texts_extra.db"), uri=True); npages = dict(x.execute("SELECT book, count(*) FROM pages GROUP BY book"))
entries = []; works = {}
for d in srt:
    slug = d["slug"]; assert slug not in own_ids, slug
    ed = d.get("edition_of"); ow = d.get("own_library_work")
    if ow and ow.get("relation") == "same work" and ow["work"] in own_works: work, wt, sid = ow["work"], ow["title"], None
    elif ed: work, wt, sid = "sh%d" % ed["shamela_id"], strip(ed["title"]), ed["shamela_id"]
    else: work, wt, sid = slug, d["title"], None
    shelf = d.get("shelf") if d.get("shelf") in SHELVES else "غير مصنف"
    e = {"id": slug, "work": work, "work_title": wt, "title": d["title"], "author": ar.get(slug) or d.get("author") or "", "author_latin": d.get("author"), "died": d.get("year") if isinstance(d.get("year"), int) and 0 < d["year"] <= 1448 else None,
         "digital": True, "store": "extra", "pages": npages.get(slug, 0), "shelf": shelf, "edition": "Imported text (extra corpus)", "source": SOURCE, "relation": d.get("why"), "chars": d.get("chars")}
    if sid: e["shamela_id"] = sid
    if d.get("new_share") is not None: e["new_share"] = d["new_share"]
    if d.get("flag"): e["note"] = d["flag"]
    entries.append(e); works.setdefault(work, []).append(e)
for work, es in works.items():                               # first place among the imported editions of a work: the fullest one; an own primary edition keeps its place
    es.sort(key=lambda e: -(e.get("chars") or 0))
    for i, e in enumerate(es): e["primary"] = bool(i == 0 and work not in own_works)
for e in entries:
    con.execute("INSERT INTO books(id, title, author, edition, source, img, pages, work, work_title, kind, primary_ed, shelf, died, store, author_latin, shamela_id, relation, new_share, note, chars) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (e["id"], e["title"], e["author"], e["edition"], e["source"], None, e["pages"], e["work"], e["work_title"], "imported", int(e["primary"]), e["shelf"], e["died"], "extra", e["author_latin"], e.get("shamela_id"), e["relation"], e.get("new_share"), e.get("note"), e["chars"]))
con.commit()
bj = [b for b in json.load(open(os.path.join(LIB, "books.json"), encoding="utf-8")) if b.get("store") != "extra"]
for b in bj: b["shelf"] = OWN.get(b.get("work", b["id"]), "غير مصنف")
json.dump(bj + entries, open(os.path.join(LIB, "books.json.tmp"), "w", encoding="utf-8"), ensure_ascii=False, indent=0); os.replace(os.path.join(LIB, "books.json.tmp"), os.path.join(LIB, "books.json"))
# the Shamela editions these works have: size, and how much of each is editor's notes (for "which edition comes first")
import semcore
S = semcore.Searcher(os.path.join(SEM, "data"), load_model=False); by = {b["shamela_id"]: b for b in S.books}; refs = {}
for sid in sorted({e["shamela_id"] for e in entries if e.get("shamela_id")}):
    b = by.get(sid)
    if not b: continue
    notes = sum(int((np.asarray(S.meta[a:z, 6]) == 1).sum()) for a, z in b["ranges"])
    refs[str(sid)] = {"title": b["title"], "author": b.get("author"), "died": b.get("death"), "shelf": b.get("cat_name"), "passages": b["passages"], "notes_passages": notes}
json.dump(refs, open(os.path.join(LIB, "shamela_refs.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("REGISTERED imported books %d | works %d (of them under a Shamela work: %d) | own books kept %d | books in the table now %d | Shamela editions referenced %d"
      % (len(entries), len(works), sum(1 for w in works if w.startswith("sh")), len(own_ids), con.execute("SELECT count(*) FROM books").fetchone()[0], len(refs)))
