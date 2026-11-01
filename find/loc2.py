import subprocess, sys, re, pathlib
for f in sorted(pathlib.Path(sys.argv[1]).glob("*_text.pdf")):
    txt = subprocess.run(["pdftotext", str(f), "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    hits = []
    for i, p in enumerate(pages, 1):
        p2 = re.sub("[‪-‮‎‏]", "", p)
        a = len(re.findall("درهمين|الدرهمين|بدرهمين", p2)); b = len(re.findall("الحرب", p2)); c=len(re.findall("حربي|الحربي|أهل الحرب|اهل الحرب",p2))
        if a and b and c: hits.append((i,a,b,c))
    print(f.name, len(pages), hits[:30], flush=True)
