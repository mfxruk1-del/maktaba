"""The catalogue of the Maktaba library as one web page (GET /library): groups, shelves with their descriptions, every work with its editions,
the fullest edition with editor's notes in first place. Book list only, no book text. Data: library.db (books), categories.json, shamela_refs.json."""
import html, json, os, pathlib, sqlite3, time

ROOT = pathlib.Path(os.environ.get("MAKTABA_DIR", ".")).resolve()
_cache = {"t": 0, "html": ""}


def _load(name, default):
    try: return json.loads((ROOT / name).read_text(encoding="utf-8"))
    except Exception: return default


def data():
    con = sqlite3.connect(f"file:{ROOT / 'library.db'}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(books)")}
    get = lambda r, k: r[k] if k in cols else None
    cats = _load("categories.json", []); refs = _load("shamela_refs.json", {})
    shelves = [s["ar"] for g in cats for s in g["shelves"]] or ["غير مصنف"]; si = {s: i for i, s in enumerate(shelves)}
    works = {}
    for r in con.execute("SELECT * FROM books ORDER BY work_title, primary_ed DESC, id"):
        w = works.setdefault(r["work"], {"t": r["work_title"] or r["title"], "a": r["author"] or "", "l": get(r, "author_latin") or "", "d": get(r, "died"), "s": si.get(get(r, "shelf") or "غير مصنف", len(shelves) - 1), "e": [], "sh": None})
        own = (get(r, "store") or "own") != "extra"; size = int((get(r, "chars") or 0) / 640) or (r["pages"] or 0) * 2
        w["e"].append({"src": "Maktaba", "id": r["id"], "t": r["edition"] if own else (r["title"] if r["title"] != w["t"] else ""), "k": r["kind"] or "", "p": r["pages"] or 0, "size": size,
                       "notes": own, "new": get(r, "new_share"), "note": get(r, "note") or "", "own": own, "prim": bool(r["primary_ed"])})
        if get(r, "shamela_id") and str(r["shamela_id"]) in refs: w["sh"] = (r["shamela_id"], refs[str(r["shamela_id"])])
    out = []
    for w in works.values():
        eds = w["e"]
        if w["sh"]:
            sid, x = w["sh"]; eds.append({"src": "Shamela", "id": sid, "t": x["title"], "k": "typed", "p": 0, "size": x["passages"], "notes": x["notes_passages"] > 0, "new": None,
                                          "note": ("editor's notes: %d%% of the text" % round(100 * x["notes_passages"] / max(1, x["passages"]))) if x["notes_passages"] else "", "own": False, "prim": False})
        eds.sort(key=lambda e: (not e["notes"], 0 if (e["own"] and e["prim"]) else 1, -e["size"]))          # editor's notes first (an own primary edition leads the own ones), then the fullest
        out.append([w["t"], w["a"], w["l"], w["d"], w["s"], [[e["src"], str(e["id"]), e["t"] or "", e["k"], e["p"], e["size"], int(bool(e["notes"])), e["new"], e["note"]] for e in eds]])
    n_books = sum(1 for w in works.values() for e in w["e"] if e["src"] == "Maktaba")
    return {"cats": cats, "shelves": shelves, "works": out, "books": n_books, "built": time.strftime("%d %b %Y", time.gmtime())}


CSS = """
:root{--p:#1e6a2b;--p-deep:#0b2410;--p-glow:#3f9a4e;--g:#d9b25c;--g-ink:#8a6a1e;--ink:#edf3ee;--cream:#f8f7f2;--text:#17301c;--muted:#5d6f61;--line:#d9b25c55}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--cream);color:var(--text);font:15px/1.55 "IBM Plex Sans","IBM Plex Sans Arabic",system-ui,sans-serif}
.ar{font-family:"Amiri","Noto Naskh Arabic",serif;direction:rtl;unicode-bidi:isolate}.kufi{font-family:"Reem Kufi","IBM Plex Sans Arabic",sans-serif}
.hero{position:relative;min-height:74vh;display:grid;place-items:center;text-align:center;color:var(--ink);overflow:hidden;padding:90px 16px 70px;
 background:radial-gradient(120% 85% at 50% 0%,#2a8a3a 0%,var(--p) 34%,var(--p-deep) 78%,#061408 100%)}
.hero svg.rose{position:absolute;left:50%;top:46%;width:min(1100px,150vw);transform:translate(-50%,-50%);opacity:.5;pointer-events:none}
.hero .in{position:relative;max-width:760px;width:100%}
.mark{width:44px;height:44px;margin:0 auto 14px;display:block}
h1{font:600 clamp(40px,7vw,62px)/1.05 "Reem Kufi","IBM Plex Sans",sans-serif;letter-spacing:.01em;margin:0}
.sub{color:var(--g);font-size:11.5px;letter-spacing:.24em;text-transform:uppercase;margin:12px 0 26px;font-weight:600}
.search{display:flex;align-items:center;gap:10px;background:#ffffffd9;border-radius:999px;padding:13px 20px;box-shadow:0 10px 30px #00000040;max-width:560px;margin:0 auto}
.search input{flex:1;border:0;outline:0;background:transparent;font:inherit;font-size:16px;color:#17301c;min-width:0}
.pills{margin-top:18px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.btn{border-radius:999px;padding:10px 20px;font-weight:600;font-size:13.5px;cursor:pointer;border:1px solid var(--g);text-decoration:none;display:inline-block}
.btn.gold{background:linear-gradient(150deg,#f1d894,var(--g) 55%,#b98f35);color:var(--p-deep);border-color:transparent}.btn.line{background:#1e6a2b99;color:var(--ink)}
.bar{position:sticky;top:10px;z-index:5;margin:10px auto 0;max-width:1180px;width:calc(100% - 24px);display:flex;align-items:center;gap:14px;padding:10px 18px;border-radius:18px;
 background:#143d1bf0;border:1px solid var(--line);color:var(--ink);backdrop-filter:blur(16px) saturate(1.7);box-shadow:0 10px 30px #00000033}
.bar b{font:600 17px "Reem Kufi","IBM Plex Sans",sans-serif}.bar .crumb{color:#edf3eeb0;font-size:13px;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar a{color:var(--ink);text-decoration:none;font-size:13.5px;padding:6px 12px;border-radius:999px;cursor:pointer}.bar a:hover{background:#ffffff1a}
main{position:relative;max-width:1180px;margin:0 auto;padding:34px 16px 80px}
main:before{content:"";position:fixed;inset:0;z-index:-1;background:radial-gradient(40% 35% at 8% 30%,#9fd3a955,transparent 70%),radial-gradient(38% 34% at 96% 78%,#e9c97a55,transparent 70%)}
h2{font:600 24px "Reem Kufi","IBM Plex Sans",sans-serif;margin:6px 0 4px}.lead{color:var(--muted);margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.tile{position:relative;overflow:hidden;text-align:start;border-radius:22px;border:1px solid var(--line);padding:16px 16px 14px;cursor:pointer;color:var(--ink);
 background:linear-gradient(160deg,#235f2d,#17421f);box-shadow:0 10px 26px #0b241026;transition:transform .15s}
.tile:hover{transform:translateY(-2px)}.tile .n{font-family:"Reem Kufi",sans-serif;color:var(--g);font-size:25px;line-height:1.5;direction:rtl;text-align:start;unicode-bidi:plaintext}
.tile .e{font-size:13.5px;color:#edf3eed9}.tile .c{font-size:12px;color:var(--g);margin-top:8px;letter-spacing:.04em}.tile .d{font-size:12.5px;color:#edf3eeb5;margin-top:6px}
.tile svg{position:absolute;right:-18px;top:-18px;width:84px;opacity:.35}
.work{background:#fffffff2;border:1px solid #17301c1a;border-radius:16px;padding:12px 16px;margin:0 0 10px;box-shadow:0 4px 14px #0b241010}
.work .t{font:700 20px/1.6 "Amiri",serif;direction:rtl;text-align:right}.work .a{color:var(--muted);font-size:13px;display:flex;gap:10px;flex-wrap:wrap;justify-content:space-between}
.ed{display:flex;gap:10px;align-items:baseline;border-top:1px dashed #17301c22;margin-top:8px;padding-top:8px;font-size:13px;flex-wrap:wrap}
.rank{flex:none;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:12px;background:#e9efe9;color:var(--muted)}
.rank.first{background:linear-gradient(150deg,#f1d894,var(--g));color:var(--p-deep)}
.src{font-size:11px;letter-spacing:.06em;text-transform:uppercase;border-radius:999px;padding:2px 9px;border:1px solid var(--line);color:var(--g-ink);flex:none}
.src.s{background:#1e6a2b;color:#fff;border-color:transparent}.ed .x{flex:1;min-width:180px}.ed .m{color:var(--muted)}
.more{display:block;margin:16px auto;}.foot{color:var(--muted);font-size:12.5px;text-align:center;margin-top:40px}
@media(max-width:560px){.bar a.h{display:none}}
"""

JS = """
const D=JSON.parse(document.getElementById('d').textContent),$=s=>document.querySelector(s),E=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f\\u064b-\\u0652\\u0670\\u0640ʿʾ'’]/g,'').replace(/[أإآٱ]/g,'ا').replace(/ى/g,'ي').replace(/ة/g,'ه');
const star='<svg viewBox="0 0 100 100" fill="none" stroke="#d9b25c" stroke-width="1.6"><rect x="22" y="22" width="56" height="56"/><rect x="22" y="22" width="56" height="56" transform="rotate(45 50 50)"/><circle cx="50" cy="50" r="17"/></svg>';
const count=D.shelves.map(()=>0);D.works.forEach(w=>count[w[4]]++);let shelfIndex={};D.shelves.forEach((s,i)=>shelfIndex[s]=i);
const main=$('#main'),crumb=$('#crumb');let shown=[],page=0;
function home(){crumb.textContent=D.works.length.toLocaleString()+' works · '+D.books.toLocaleString()+' books';main.innerHTML='';main.append(E('h2','', 'The shelves'),E('p','lead','Eight halls. Open one to see its shelves, then the works on each shelf.'));
 const g=E('div','grid');D.cats.forEach((c,i)=>{const n=c.shelves.reduce((a,s)=>a+count[shelfIndex[s.ar]],0);const t=E('div','tile',star+'<div class="n">'+esc(c.ar)+'</div><div class="e">'+esc(c.en)+'</div><div class="c">'+n.toLocaleString()+' works · '+c.shelves.length+' shelves</div>');t.onclick=()=>{location.hash='g'+i};g.append(t)});main.append(g)}
function group(i){const c=D.cats[i];crumb.textContent=c.en;main.innerHTML='';main.append(E('h2','',esc(c.en)+' <span class="kufi" style="color:#8a6a1e">· '+esc(c.ar)+'</span>'),E('p','lead','Choose a shelf.'));
 const g=E('div','grid');c.shelves.forEach(s=>{const k=shelfIndex[s.ar];const t=E('div','tile',star+'<div class="n">'+esc(s.ar)+'</div><div class="d">'+esc(s.en)+'</div><div class="c">'+count[k].toLocaleString()+' works</div>');t.onclick=()=>{location.hash='s'+k};g.append(t)});main.append(g)}
function work(w){const d=E('div','work');let h='<div class="t">'+esc(w[0])+'</div><div class="a"><span>'+(w[3]?'d. '+w[3]+' AH':'')+'</span><span>'+(w[2]?esc(w[2])+' · ':'')+'<span class="ar">'+esc(w[1]&&w[1]!==w[2]?w[1]:'')+'</span></span></div>';
 w[5].forEach((e,i)=>{const sh=e[0]==='Shamela';let m=[];if(e[3]&&!sh)m.push(e[3]==='imported'?'imported text':e[3]+' text');if(e[4])m.push(e[4].toLocaleString()+' pages');else if(e[5])m.push('about '+e[5].toLocaleString()+' passages');
  if(e[7]!=null&&e[7]>0)m.push('about '+Math.round(e[7]*100)+'% of it is not in Shamela');if(e[8])m.push(esc(e[8]));
  h+='<div class="ed"><span class="rank'+(i===0?' first':'')+'" title="'+(i===0?'First place: editor\\'s notes and the fullest text':'')+'">'+(i+1)+'</span><span class="src'+(sh?' s':'')+'">'+e[0]+'</span><span class="x ar">'+esc(e[2])+'</span><span class="m">'+m.join(' · ')+'</span></div>'});
 d.innerHTML=h;return d}
function list(ws,title,lead){main.innerHTML='';main.append(E('h2','',title),E('p','lead',lead));shown=ws;page=0;const box=E('div');box.id='box';main.append(box);const b=E('button','btn gold more','Show more');b.id='more';b.onclick=more;main.append(b);more()}
function more(){const box=$('#box');shown.slice(page*60,page*60+60).forEach(w=>box.append(work(w)));page++;$('#more').style.display=page*60>=shown.length?'none':'block'}
function shelf(k){const name=D.shelves[k];let desc='';D.cats.forEach(c=>c.shelves.forEach(s=>{if(s.ar===name)desc=s.en}));crumb.textContent=name;const ws=D.works.filter(w=>w[4]===k).sort((a,b)=>(a[3]||9999)-(b[3]||9999));
 list(ws,'<span class="kufi">'+esc(name)+'</span>',esc(desc)+' '+ws.length.toLocaleString()+' works, oldest author first. The numbered circle shows the order of the editions: editor\\'s notes and the fullest text come first.')}
function find(q){const n=norm(q).trim();if(!n){route();return}const ws=D.works.filter(w=>norm(w[0]).includes(n)||norm(w[1]).includes(n)||norm(w[2]).includes(n));crumb.textContent='Search';list(ws,'Search: '+esc(q),ws.length.toLocaleString()+' works match in title or author.');document.getElementById('top').scrollIntoView()}
function route(){const h=location.hash.slice(1);if(h[0]==='g'&&D.cats[+h.slice(1)])group(+h.slice(1));else if(h[0]==='s'&&D.shelves[+h.slice(1)])shelf(+h.slice(1));else home();if(h)document.getElementById('top').scrollIntoView()}
window.onhashchange=route;route();const q=$('#q');q.onkeydown=e=>{if(e.key==='Enter')find(q.value)};$('#go').onclick=()=>find(q.value);
"""


def render():
    if time.time() - _cache["t"] < 600 and _cache["html"]: return _cache["html"]
    d = data(); rose = "".join('<polygon points="%s" transform="rotate(%d 500 500)"/>' % (" ".join("%d,%d" % (500 + r * c, 500 + r * s) for c, s in ((1, 0), (0, 1), (-1, 0), (0, -1))), a) for r in (150, 250, 350, 450) for a in (0, 30, 60))
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name='robots' content='noindex'>"
            "<meta name='theme-color' content='#184A1D'><title>Maktaba · the library</title><link rel='preconnect' href='https://fonts.googleapis.com'>"
            "<link href='https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Sans+Arabic:wght@400;600&family=Reem+Kufi:wght@500;600&display=swap' rel='stylesheet'>"
            "<style>" + CSS + "</style></head><body><header class='hero'><svg class='rose' viewBox='0 0 1000 1000' fill='none' stroke='#d9b25c' stroke-width='1'>" + rose +
            "<circle cx='500' cy='500' r='150'/><circle cx='500' cy='500' r='250'/><circle cx='500' cy='500' r='350'/><circle cx='500' cy='500' r='450'/></svg><div class='in'>"
            "<svg class='mark' viewBox='0 0 48 48' fill='none' stroke='#d9b25c' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M24 12c-5-3-10-3-16-2v26c6-1 11-1 16 2 5-3 10-3 16-2V10c-6-1-11-1-16 2zM24 12v26'/></svg>"
            "<h1>Maktaba</h1><div class='sub'>The library · @@W@@ works · @@B@@ books</div><div class='search'><svg width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='#5d6f61' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='M20 20l-3.500-3.500'/></svg>"
            "<input id='q' placeholder='Search a title or an author, Arabic or Latin letters' autocomplete='off'></div><div class='pills'><a class='btn gold' id='go'>Search the catalogue</a><a class='btn line' href='#top'>Browse the shelves</a></div></div></header>"
            "<div class='bar' id='top'><b>Maktaba</b><span class='crumb' id='crumb'></span><a class='h' href='#'>Shelves</a><a class='h' href='/'>Status</a></div><main id='main'></main>"
            "<p class='foot'>Book list only, no book text. Editions of the same work stand together; the first place goes to the edition with editor's notes and the fullest text. Updated @@D@@.</p>"
            "<script id='d' type='application/json'>@@DATA@@</script><script>@@JS@@</script></body></html>")
    page = (page.replace("@@W@@", format(len(d["works"]), ",")).replace("@@B@@", format(d["books"], ",")).replace("@@D@@", html.escape(d["built"]))
            .replace("@@JS@@", JS).replace("@@DATA@@", json.dumps(d, ensure_ascii=False).replace("</", "<\\/")))
    _cache.update(t=time.time(), html=page); return page
