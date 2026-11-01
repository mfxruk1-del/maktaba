import subprocess, sys, re, pathlib
pats = [r"دار\s*الحرب", r"درهم[اًا]?\s*بدرهمين", r"الصرف", r"القمار|يقامر|قامر"]
for f in sorted(pathlib.Path(sys.argv[1]).glob("*_text.pdf")):
    txt = subprocess.run(["pdftotext", str(f), "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    hits = []
    for i, p in enumerate(pages, 1):
        p2 = p.replace("‫", "").replace("‬", "")
        s = [len(re.findall(x, p2)) for x in pats]
        if s[0] and (s[1] or s[3]):
            hits.append((i, s))
    print(f.name, len(pages), "pages;", hits[:20])
