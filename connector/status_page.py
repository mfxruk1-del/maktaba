"""Public status page for the Maktaba library: OCR progress, works, editions and quality. Metadata only, no book text."""
import html, json, os, pathlib, sqlite3, subprocess, time

ROOT = pathlib.Path(os.environ.get("MAKTABA_DIR", ".")).resolve()
_cache = {"t": 0, "html": ""}
_pages = {}   # pdf path -> page count


def _pdf_pages(p):
    if p not in _pages:
        try:
            out = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True, timeout=20).stdout
            _pages[p] = int(next(l.split()[1] for l in out.splitlines() if l.startswith("Pages:")))
        except Exception:
            return 0
    return _pages[p]


def _count(d, suffix):
    try:
        return sum(1 for f in os.scandir(d) if f.name.endswith(suffix) and f.stat().st_size > 0)
    except FileNotFoundError:
        return 0


def _recent(d, since):
    try:
        return sum(1 for f in os.scandir(d) if f.name.endswith(".txt") and f.stat().st_mtime >= since)
    except FileNotFoundError:
        return 0


def _ocr_jobs(indexed):
    try:
        queue = json.loads((ROOT / "ocr_queue.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        queue = []
    jobs, since = [], time.time() - 1800
    for q in queue:
        d = ROOT / "ocr" / f"{q['id']}_ocr"
        pdf = ROOT / "ocr" / f"{q['id']}.pdf"
        src = pdf if pdf.exists() else ROOT / "cand" / q.get("cand", "")
        total = _pdf_pages(src) if src.is_file() else 0
        done = _count(d / "raw", ".txt")
        rendered = _count(d / "img", ".png")
        if q["id"] in indexed:
            state = "In the library"
        elif (d / f"{q['id']}.jsonl").exists() and total and done >= total:
            state = "OCR finished, checking"
        elif done or rendered:
            state = "Rendering pages" if not done else "OCR running"
        else:
            state = "Queued"
        jobs.append(dict(q, total=total, done=min(done, total) if total else done, state=state,
                         recent=_recent(d / "raw", since)))
    rate = sum(j["recent"] for j in jobs) / 30  # pages per minute over the last 30 minutes
    remaining = sum(max(j["total"] - j["done"], 0) for j in jobs if j["state"] not in ("In the library",))
    return jobs, rate, remaining


def _esc(s):
    return html.escape(str(s or ""))


def render():
    if time.time() - _cache["t"] < 30:
        return _cache["html"]
    books = json.loads((ROOT / "books.json").read_text(encoding="utf-8"))
    try:
        quality = json.loads((ROOT / "quality.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        quality = {}
    con = sqlite3.connect(f"file:{ROOT / 'library.db'}?mode=ro", uri=True)
    pages = dict(con.execute("SELECT id, pages FROM books"))
    con.close()
    jobs, rate, remaining = _ocr_jobs(set(pages))

    # ---- OCR section
    rows = []
    for j in jobs:
        pct = int(100 * j["done"] / j["total"]) if j["total"] else 0
        if j["state"] == "In the library":
            pct = 100
        rows.append(f"""<div class="job"><div class="jobhead"><span class="t" dir="rtl">{_esc(j['title'])}</span>
          <span class="state s-{_esc(j['state'].split()[0].lower())}">{_esc(j['state'])}</span></div>
          <div class="sub">{_esc(j.get('note'))}</div>
          <div class="bar"><div style="width:{pct}%"></div></div>
          <div class="sub">{j['done']} / {j['total'] or '?'} pages · {pct}%</div></div>""")
    if rate > 0 and remaining:
        eta_min = remaining / rate
        eta = f"about {eta_min / 60:.1f} hours left" if eta_min > 90 else f"about {eta_min:.0f} minutes left"
        speed = f"Speed: {rate:.1f} pages/minute · {remaining} pages to go · {eta}"
    elif remaining:
        speed = f"{remaining} pages to go (speed shown once OCR is running)"
    else:
        speed = "Nothing in the OCR queue right now."
    ocr_html = "".join(rows) or '<p class="sub">No OCR jobs.</p>'

    # ---- library section
    works = {}
    for b in books:
        works.setdefault(b["work"], {"title": b["work_title"], "author": b["author"], "eds": []})["eds"].append(b)
    cards = []
    n_ed = 0
    for w in works.values():
        eds = sorted(w["eds"], key=lambda e: (not e.get("primary"), e["id"]))
        items = []
        for e in eds:
            n_ed += 1
            q = quality.get(e["id"], {})
            if e.get("digital"):
                badge, rating = "typed", "Exact (typed text)"
            else:
                badge, rating = "ocr", f"OCR · {e.get('rating', 'not rated yet')}"
            score = f" · word score {q['known']:.0f}%" if q.get("known") else ""
            scans = "with page scans" if e.get("img") else "no scans"
            prim = '<span class="prim">primary</span>' if e.get("primary") else ""
            items.append(f"""<li><div class="edhead"><span class="badge b-{badge}">{'Typed' if badge == 'typed' else 'OCR'}</span>
              {prim}<span class="rating r-{_esc(str(e.get('rating', 'typed' if e.get('digital') else 'x')).lower())}">{_esc(rating)}{score}</span></div>
              <div class="ed" dir="rtl">{_esc(e.get('edition'))}</div>
              <div class="sub">{pages.get(e['id'], 0)} pages · {scans} · id <code>{_esc(e['id'])}</code></div></li>""")
        cards.append(f"""<section class="work"><h3 dir="rtl">{_esc(w['title'])}</h3>
          <div class="author" dir="rtl">{_esc(w['author'])}</div>
          <div class="sub">{len(eds)} edition{'s' if len(eds) > 1 else ''}</div><ul>{''.join(items)}</ul></section>""")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="60">
<title>Maktaba Status</title>
<link href="https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f6f3ec;--card:#fffdf8;--ink:#2b2620;--muted:#7a7166;--line:#e4ddcf;--accent:#1f6f5c;--accent2:#b5832a;--bar:#e9e2d4}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16140f;--card:#201d17;--ink:#ece6da;--muted:#a59b8c;--line:#353026;--accent:#4fb39a;--accent2:#d9a85a;--bar:#2e2a22}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 60px}}
h1{{font-size:26px;margin:0}} h2{{font-size:18px;margin:32px 0 12px}} .lead{{color:var(--muted);margin:4px 0 0}}
[dir=rtl]{{font-family:Amiri,serif}} .sub{{color:var(--muted);font-size:13px}} code{{font-size:12px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.job+.job{{margin-top:16px;padding-top:16px;border-top:1px solid var(--line)}}
.jobhead{{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap}} .t{{font-size:19px}}
.bar{{height:8px;background:var(--bar);border-radius:99px;overflow:hidden;margin:8px 0 4px}} .bar div{{height:100%;background:var(--accent)}}
.state{{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}}
.s-ocr,.s-rendering{{color:var(--accent);border-color:var(--accent)}} .s-in{{color:var(--accent2);border-color:var(--accent2)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}}
.work{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.work h3{{margin:0;font-size:21px;line-height:1.4}} .author{{color:var(--muted);font-size:16px}}
.work ul{{list-style:none;padding:0;margin:10px 0 0}} .work li{{border-top:1px dashed var(--line);padding:10px 0 4px}}
.edhead{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}} .ed{{font-size:16px;margin:4px 0 2px}}
.badge,.prim{{font-size:11px;font-weight:600;padding:1px 7px;border-radius:5px}}
.b-typed{{background:var(--accent);color:#fff}} .b-ocr{{background:var(--accent2);color:#fff}} .prim{{border:1px solid var(--line);color:var(--muted)}}
.rating{{font-size:12px;color:var(--muted)}} .r-excellent{{color:var(--accent)}} .r-fair,.r-weak{{color:#b44}}
.stats{{display:flex;gap:24px;flex-wrap:wrap;margin-top:14px}} .stats b{{font-size:22px;display:block}}
</style></head><body><main>
<h1>Maktaba</h1><p class="lead">Personal Arabic library · status page · refreshes every minute</p>
<div class="stats"><div><b>{len(works)}</b><span class="sub">works</span></div><div><b>{n_ed}</b><span class="sub">editions</span></div>
<div><b>{sum(pages.values()):,}</b><span class="sub">pages indexed</span></div></div>
<h2>OCR progress</h2><div class="panel">{ocr_html}<p class="sub" style="margin:14px 0 0">{_esc(speed)}</p></div>
<h2>Library</h2><div class="grid">{''.join(cards)}</div>
<p class="sub" style="margin-top:28px">Typed = digital text matched to the print (exact). OCR = machine-read from scans; the rating is from
checking pages against the scans, and the word score is the share of words found in a vocabulary of the typed books (a rough guide:
typed books score 94–99%). Updated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}.</p>
</main></body></html>"""
    _cache.update(t=time.time(), html=page)
    return page
