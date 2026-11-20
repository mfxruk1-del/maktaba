#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notebook of verified findings: SQLite store with add / search / show / export-markdown / seed.

Run with ~/semsearch/venv/bin/python notebook.py <command> ...   (see README.md)
Arabic matching uses semcore.toks (normalise + strip al-/wa-al- etc.) so word forms match.
"""
import argparse, datetime, json, os, re, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from semcore import toks  # only reads text, loads no data or model

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "findings.sqlite3")
SPEAKERS = ("author", "quoted", "opponent", "editor")

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT NOT NULL,              -- main question / topic tag
  shamela_id INTEGER NOT NULL, title TEXT, author TEXT, died_ah INTEGER,
  part INTEGER NOT NULL, page INTEGER NOT NULL, shamela_page_id INTEGER,
  kind TEXT NOT NULL DEFAULT 'm',   -- m main text, f editor's footnote
  speaker TEXT, quotes TEXT,        -- who speaks; whom he quotes
  arabic TEXT NOT NULL, arabic_toks TEXT NOT NULL,   -- arabic_toks = ' tok tok ' (semcore.toks)
  gist TEXT, checked_by TEXT, checked_at TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(shamela_id, part, page, kind, topic)
);
CREATE TABLE IF NOT EXISTS tags(finding_id INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  tag TEXT NOT NULL, PRIMARY KEY(finding_id, tag));
CREATE INDEX IF NOT EXISTS ix_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS ix_f_book ON findings(shamela_id);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def add(con, topic, shamela_id, part, page, arabic, tags=(), title="", author="", died_ah=None,
        shamela_page_id=None, kind="m", speaker=None, quotes="", gist="", checked_by="", checked_at=None,
        status="unchecked"):
    """Insert a finding. Returns (id, True) if new, (id, False) if the same page+topic already exists
    (then only missing tags are merged in; nothing else is overwritten)."""
    topic = topic.strip()
    if speaker and speaker.lower() not in SPEAKERS:
        raise ValueError("speaker must be one of %s" % (SPEAKERS,))
    speaker = speaker.lower() if speaker else None
    row = con.execute("SELECT id FROM findings WHERE shamela_id=? AND part=? AND page=? AND kind=? AND topic=?",
                      (shamela_id, part, page, kind, topic)).fetchone()
    new = row is None
    if new:
        cur = con.execute(
            "INSERT INTO findings(topic,shamela_id,title,author,died_ah,part,page,shamela_page_id,kind,speaker,quotes,"
            "arabic,arabic_toks,gist,checked_by,checked_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (topic, shamela_id, title, author, died_ah, part, page, shamela_page_id, kind, speaker, quotes, arabic,
             " " + " ".join(toks(arabic)) + " ", gist, checked_by, checked_at or (now() if checked_by else None),
             status, now()))
        fid = cur.lastrowid
    else:
        fid = row["id"]
    for t in {topic, *[x.strip() for x in tags if x and x.strip()]}:
        con.execute("INSERT OR IGNORE INTO tags VALUES(?,?)", (fid, t))
    con.commit()
    return fid, new


def search(con, tag=None, book=None, author=None, arabic=None, status=None, limit=50):
    """All given filters must match. book: shamela_id (digits) or title substring.
    arabic: every word (after semcore.toks) must occur in the passage, so 'المشتري' finds 'والمشتري'."""
    where, args = [], []
    if tag:
        where.append("f.id IN (SELECT finding_id FROM tags WHERE tag=?)"); args.append(tag)
    if book:
        if str(book).isdigit():
            where.append("f.shamela_id=?"); args.append(int(book))
        else:
            where.append("f.title LIKE ?"); args.append("%" + book + "%")
    if author:
        where.append("f.author LIKE ?"); args.append("%" + author + "%")
    if status:
        where.append("f.status LIKE ?"); args.append(status + "%")
    if arabic:
        words = toks(arabic)
        if not words:
            return []
        for w in words:
            where.append("f.arabic_toks LIKE ?"); args.append("% " + w + " %")
    sql = "SELECT f.* FROM findings f" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY f.id LIMIT ?"
    return con.execute(sql, args + [limit]).fetchall()


def tags_of(con, fid):
    return [r[0] for r in con.execute("SELECT tag FROM tags WHERE finding_id=? ORDER BY tag", (fid,))]


def fmt(con, r, full=True):
    head = "#%d [%s] %s | %s (d. %s AH) | part %s p. %s%s | %s | %s" % (
        r["id"], r["topic"], r["title"], r["author"], r["died_ah"], r["part"], r["page"],
        "" if r["kind"] == "m" else " (footnote)", "speaks: %s" % (r["speaker"] or "?"), r["status"])
    if not full:
        return head
    return "\n".join([head, "  tags: " + ", ".join(tags_of(con, r["id"])),
                      "  shamela_id %s, shamela_page_id %s; quotes: %s" % (r["shamela_id"], r["shamela_page_id"], r["quotes"] or "-"),
                      "  checked: %s %s" % (r["checked_by"] or "-", r["checked_at"] or ""),
                      "  gist: " + (r["gist"] or ""), "  arabic: " + r["arabic"]])


def export_markdown(con, path=None, tag=None):
    rows = search(con, tag=tag, limit=10**6)
    by = {}
    for r in rows:
        by.setdefault(r["topic"], []).append(r)
    out = ["# Notebook of verified findings", "", "%d findings, exported %s." % (len(rows), now()), ""]
    for topic, rs in sorted(by.items()):
        out += ["## " + topic, ""]
        for r in rs:
            out += ["### #%d %s" % (r["id"], r["title"] or ""),
                    "- Author: %s (d. %s AH); part %s, page %s%s; shamela_id %s, shamela_page_id %s" % (
                        r["author"], r["died_ah"], r["part"], r["page"], "" if r["kind"] == "m" else " (editor's footnote)",
                        r["shamela_id"], r["shamela_page_id"]),
                    "- Speaks: %s; quotes: %s" % (r["speaker"] or "?", r["quotes"] or "-"),
                    "- Gist: %s" % (r["gist"] or ""),
                    "- Status: %s (checked by %s %s)" % (r["status"], r["checked_by"] or "-", r["checked_at"] or ""),
                    "- Tags: " + ", ".join(tags_of(con, r["id"])), "",
                    "> " + r["arabic"].replace("\n", "\n> "), ""]
    text = "\n".join(out)
    if path:
        open(path, "w", encoding="utf-8").write(text)
    return text


def seed(con, tests=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"), data=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")):
    """r4_truth_items.json joined (by id) to helper/ans_tc_*.jsonl, verdict HOLDS only."""
    import glob
    import numpy as np
    items = {x["id"]: x for x in json.load(open(os.path.join(tests, "r4_truth_items.json"), encoding="utf-8"))}
    ans = {}
    for f in sorted(glob.glob(os.path.join(tests, "helper", "ans_tc_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                a = json.loads(line); ans[a["id"]] = a
    books = {b["shamela_id"]: b for b in json.load(open(os.path.join(data, "books.json"), encoding="utf-8"))}
    meta = np.load(os.path.join(data, "meta.npy"), mmap_mode="r")
    stats = dict(holds=0, new=0, dup=0, unresolved=0)
    for i, a in sorted(ans.items()):
        if a.get("verdict") != "HOLDS" or i not in items:
            continue
        stats["holds"] += 1
        it, b = items[i], books.get(items[i]["book_id"])
        if not b:
            stats["unresolved"] += 1; continue
        spid, kind = None, 0
        for lo, hi in b["ranges"]:
            m = meta[lo:hi]
            hit = np.where(m[:, 3] == it["page_id"])[0]
            if len(hit):
                spid, kind = int(m[hit[0], 3]), int(m[hit[0], 6]); break
        q = re.search(r'"([^"]+)"', it["question"])
        topic = it["q"]
        tags = [topic, "mark:" + it["mark"]] + ([q.group(1)[:80]] if q else [])
        sp = (a.get("speaker") or "").lower()
        _, new = add(con, topic, b["shamela_id"], it["part"], it["page"], it["text"], tags=tags, title=b["title"],
                     author=b["author"], died_ah=None if b["death"] == 99999 else b["death"], shamela_page_id=spid,
                     kind="f" if kind == 1 else "m", speaker=sp if sp in SPEAKERS else None, gist=a.get("reason", ""),
                     checked_by="strong model (judged on the real page)", checked_at="2026-11-19",
                     status="page checked by a model, not yet by a person")
        stats["new" if new else "dup"] += 1
    return stats


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("add"); a.add_argument("--topic", required=True); a.add_argument("--shamela-id", type=int, required=True)
    a.add_argument("--part", type=int, required=True); a.add_argument("--page", type=int, required=True)
    a.add_argument("--arabic", required=True); a.add_argument("--tags", default="")
    for k in ("title", "author", "gist", "quotes", "checked-by", "status", "speaker", "kind"):
        a.add_argument("--" + k, default={"status": "unchecked", "kind": "m"}.get(k, ""))
    a.add_argument("--died-ah", type=int); a.add_argument("--shamela-page-id", type=int)
    q = s.add_parser("search"); [q.add_argument("--" + k) for k in ("tag", "book", "author", "arabic", "status")]
    q.add_argument("--limit", type=int, default=50); q.add_argument("--brief", action="store_true")
    sh = s.add_parser("show"); sh.add_argument("id", type=int)
    e = s.add_parser("export-markdown"); e.add_argument("--out"); e.add_argument("--tag")
    s.add_parser("seed")
    args = p.parse_args(argv)
    con = connect(args.db)
    if args.cmd == "add":
        fid, new = add(con, args.topic, args.shamela_id, args.part, args.page, args.arabic,
                       tags=[t for t in args.tags.split(",") if t], title=args.title, author=args.author, died_ah=args.died_ah,
                       shamela_page_id=args.shamela_page_id, kind=args.kind, speaker=args.speaker or None, quotes=args.quotes,
                       gist=args.gist, checked_by=args.checked_by, status=args.status)
        print(("added #%d" if new else "duplicate of #%d (tags merged, nothing else changed)") % fid)
    elif args.cmd == "search":
        rows = search(con, args.tag, args.book, args.author, args.arabic, args.status, args.limit)
        for r in rows:
            print(fmt(con, r, full=not args.brief))
        print("%d result(s)" % len(rows))
    elif args.cmd == "show":
        r = con.execute("SELECT * FROM findings WHERE id=?", (args.id,)).fetchone()
        print(fmt(con, r) if r else "no such finding")
    elif args.cmd == "export-markdown":
        t = export_markdown(con, args.out, args.tag)
        print("wrote " + args.out if args.out else t)
    elif args.cmd == "seed":
        print(json.dumps(seed(con)))


if __name__ == "__main__":
    main()
