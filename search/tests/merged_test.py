# -*- coding: utf-8 -*-
"""Tests for the ONE Maktaba library (own + imported books): the search service, the connector end to end, the catalogue page.
   sudo ~/library/maktaba-venv/bin/python ~/semsearch/tests/merged_test.py      (root only to read the connector's address and secret path from /etc/maktaba.env; nothing is printed of it)
Read-only: searches and page reads. Prints PASS / FAIL per test; exit code 1 when any fails."""
import asyncio, json, re, sys, urllib.request, urllib.error
SVC = "http://127.0.0.1:8791"; R = []


def post(path, payload, timeout=120):
    req = urllib.request.Request(SVC + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode("utf-8"))
        except Exception: return e.code, {}


def t(name, ok, line):
    R.append(bool(ok)); print("%s  %s: %s" % ("PASS" if ok else "FAIL", name, str(line)[:300]), flush=True)


PH = ["الشرب قائما"]
st, b = post("/books", {"library": "maktaba", "limit": 3}); t("1 one index", st == 200 and b.get("matched", 0) > 2000, "%s books, %s passages in the Maktaba index" % (b.get("matched"), b.get("passages")))
st, n1 = post("/near", {"library": "maktaba", "phrases": PH, "limit": 8, "chars": 300}); rows = n1.get("results") or []
imp = [x for x in rows if x.get("text_kind") == "imported"]
t("2 nearby-words reaches imported books", st == 200 and imp and all(x.get("library") == "maktaba" and x.get("book") for x in rows), "%s hits in %s books; %d of %d rows from imported books; first: %s p%s shelf %s" % (
    n1.get("total_hits"), n1.get("books_with_hits"), len(imp), len(rows), (imp or [{}])[0].get("book"), (imp or [{}])[0].get("page"), (imp or [{}])[0].get("shelf")))
st, n2 = post("/near", {"library": "kutub", "phrases": PH, "limit": 8}); t("3 the old name 'kutub' is read as maktaba", st == 200 and n2.get("total_hits") == n1.get("total_hits"), "same %s hits" % n2.get("total_hits"))
st, s1 = post("/search", {"library": "maktaba", "query": "حكم الشرب قائما", "limit": 5}); t("4 meaning-search", st == 200 and len(s1.get("results") or []) > 0, "%d rows; first: %s" % (len(s1.get("results") or []), ((s1.get("results") or [{}])[0]).get("title")))
st, d1 = post("/digest", {"library": "maktaba", "phrases": PH, "queries": ["حكم الشرب قائما"]}, 280); lines = [l for l in (d1.get("digest") or "").split("\n") if re.match(r"\d+\. ", l)]
t("5 digest", st == 200 and lines, "%d book lines; first: %s" % (len(lines), (lines or [""])[0][:120]))
st, o1 = post("/near", {"library": "maktaba", "phrases": ["في ذلك", "على ان"], "books": ["radd-muhtar"], "limit": 3}); orow = (o1.get("results") or [{}])[0]
t("6 the owner's own books as before", st == 200 and orow.get("book", "").startswith("radd-muhtar") and orow.get("text_kind") in ("OCR", "typed"), "%s p%s (%s), scope %s" % (orow.get("book"), orow.get("page"), orow.get("text_kind"), (o1.get("scope") or {}).get("books")))
st, c1 = post("/near", {"library": "maktaba", "phrases": PH, "category": "كتب السنة", "limit": 3}); st2, c2 = post("/near", {"library": "maktaba", "phrases": PH, "author": "suyuti", "limit": 3})
t("7 shelf and Latin author filters", st == 200 and (c1.get("scope") or {}).get("books", 0) > 50 and st2 == 200 and (c2.get("scope") or {}).get("books", 0) > 0, "shelf كتب السنة: %s books in scope; author 'suyuti': %s books" % ((c1.get("scope") or {}).get("books"), (c2.get("scope") or {}).get("books")))
x = (imp or [{}])[0]; words = [w for w in re.sub("[⟪⟫«»…]", " ", x.get("text") or "").split() if re.fullmatch("[ء-ي]+", w)]
run = " ".join(words[len(words) // 2 - 3: len(words) // 2 + 3]); st, q1 = post("/mk/quote", {"book": x.get("book"), "quote": run, "page": x.get("page")})
t("8 quote check in an imported book", st == 200 and (q1.get("found") is True or q1.get("longest_run", 0) >= 3), "«%s» in %s p%s: found %s" % (run, x.get("book"), x.get("page"), q1.get("found")))

env = {}
for line in open("/etc/maktaba.env"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); env[k] = v.strip().strip('"').strip("'")
base = "http://%s:%s" % (env.get("MAKTABA_HOST", "127.0.0.1"), env.get("MAKTABA_PORT", "8790"))
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def conn():
    async with streamablehttp_client("%s/%s/mcp" % (base, env["MAKTABA_TOKEN"])) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize(); tools = [x.name for x in (await s.list_tools()).tools]; size = sum(len(x.description or "") for x in (await s.list_tools()).tools)
            call = lambda name, a: s.call_tool(name, a); J = lambda res: json.loads(res.content[0].text) if res.content else {}
            t("9 connector tools", "kutub_read_page" not in tools and {"list_books", "search", "get_page", "check_quote", "search_digest"} <= set(tools), "%d tools, descriptions %d characters: %s" % (len(tools), size, ", ".join(tools)))
            lb = J(await call("list_books", {})); t("10 list_books()", lb.get("works_in_library", 0) > 1900 and len(lb.get("shelves") or {}) > 20 and 0 < lb.get("shown", 0) <= 40, "%s works in the library, %d shelves, %s own works shown" % (lb.get("works_in_library"), len(lb.get("shelves") or {}), lb.get("shown")))
            lq = J(await call("list_books", {"query": "قاضيخان"})); wk = (lq.get("works") or [{}])[0]; ed = ((wk.get("editions") or [{}])[0]).get("id")
            t("11 list_books(query)", lq.get("matched", 0) >= 1 and ed, "%s -> %s (%s), edition %s" % (lq.get("matched"), wk.get("title"), wk.get("shelf"), ed))
            sr = J(await call("search", {"query": "كتاب الطهارة", "book": ed, "mode": "phrase", "limit": 3})); hit = (sr.get("hits") or [{}])[0]
            t("12 search inside an imported book", sr.get("count", 0) > 0 and hit.get("book") == ed, "%s hits; first p%s: %s" % (sr.get("count"), hit.get("page"), " ".join(hit.get("lines") or [])[:90]))
            gp = J(await call("get_page", {"book": ed, "page": hit.get("page", 0)})); text = ((gp.get("pages") or [{}])[0]).get("text") or ""
            tk = text.split(); qr = next((" ".join(tk[i:i + 6]) for i in range(len(tk) // 3, len(tk) - 6) if all(re.fullmatch("[ء-ي]+", w) for w in tk[i:i + 6])), ""); cq = J(await call("check_quote", {"book": ed, "quote": qr, "page": hit.get("page", 0)}))
            t("13 get_page + check_quote", len(text) > 50 and cq.get("found") is True, "page of %d characters; «%s» found: %s" % (len(text), qr, cq.get("found")))
            so = J(await call("search", {"query": "رد المحتار", "mode": "phrase", "limit": 5})); t("14 search over the whole library", so.get("count", 0) > 0, "%s hits; books: %s" % (so.get("count"), sorted({h.get("book") for h in so.get("hits") or []})[:4]))
asyncio.run(conn())
try:
    with urllib.request.urlopen(base + "/library", timeout=60) as r: page = r.read().decode("utf-8"); code = r.status
except Exception as e: page = ""; code = str(e)[:80]
t("15 the catalogue page", code == 200 and "Maktaba" in page and '"works"' in page, "status %s, %d KB" % (code, len(page) // 1024))
print("\n%d of %d tests passed" % (sum(R), len(R))); sys.exit(0 if all(R) else 1)
