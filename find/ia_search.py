import sys, json, urllib.parse, urllib.request
q = sys.argv[1]; rows = int(sys.argv[2]) if len(sys.argv) > 2 else 25
url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
    {"q": q, "fl[]": ["identifier", "title", "imagecount", "downloads", "date"], "rows": rows, "output": "json", "sort[]": "downloads desc"}, doseq=True)
d = json.load(urllib.request.urlopen(url, timeout=60))
print(d["response"]["numFound"], "found")
for r in d["response"]["docs"]:
    t = r.get("title"); t = t if isinstance(t, str) else str(t)
    print(r.get("identifier"), "|", t[:110], "| img", r.get("imagecount"), "| dl", r.get("downloads"))
