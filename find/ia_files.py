import sys, json, urllib.request, re
for item in sys.argv[1:]:
    try:
        d = json.load(urllib.request.urlopen(f"https://archive.org/metadata/{item}", timeout=60))
    except Exception as e:
        print("##", item, "ERR", e); continue
    m = d.get("metadata", {})
    desc = m.get("description", ""); desc = desc if isinstance(desc, str) else " ".join(desc)
    desc = re.sub(r"<[^>]+>", " ", desc)
    print("##", item, "|", m.get("title"), "|", m.get("date"), "| creator:", m.get("creator"))
    print("   desc:", desc[:400].replace("\n", " "))
    for f in d.get("files", []):
        n = f["name"]
        if re.search(r"\.(pdf|rar|zip|bok|docx?|epub|txt)$", n, re.I) and not n.endswith("_djvu.txt"):
            print("   ", n, f.get("size"), f.get("format"))
