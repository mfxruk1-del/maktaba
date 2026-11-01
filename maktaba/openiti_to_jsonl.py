"""Convert an OpenITI mARkdown text (from Shamela, 'matched to print') to Maktaba jsonl.

Printed page breaks are the inline #NN# markers; PageV.. lines (Shamela page index), ms milestones,
'# ' paragraph marks and '~~' continuation marks are removed. Each record: {"page", "printed", "text"};
"page" is a running number (there is no PDF), "printed" the printed page number.
Usage: python openiti_to_jsonl.py input-ara1 output.jsonl
"""
import json, re, sys

src, dst = sys.argv[1], sys.argv[2]
body = open(src, encoding="utf-8-sig").read().split("#META#Header#End#")[-1]
MARK = re.compile(r"#(\d+)#")
pages, cur, buf = [], None, []

def flush():
    text = "\n".join(l for l in (x.strip() for x in "".join(buf).splitlines()) if l)
    if text:
        pages.append((cur, text))

for line in body.splitlines():
    if re.fullmatch(r"\s*PageV\d+P\d+\s*", line):
        continue
    line = re.sub(r"PageV\d+P\d+|\bms\d+\b", "", line)
    line = re.sub(r"^### \|+ (AUTO )?", "", line)
    line = re.sub(r"^# ", "", line)
    cont = line.startswith("~~")
    line = line[2:] if cont else line
    for i, part in enumerate(MARK.split(line)):
        if i % 2:                      # a printed-page marker
            flush(); buf = []; cur = part
        else:
            buf.append(part)
    buf.append("\n")
flush()

with open(dst, "w", encoding="utf-8") as out:
    for n, (pr, text) in enumerate(pages, 1):
        if pr is None and len(pages) > 1 and pages[1][0]:
            pr = str(int(pages[1][0]) - 1)   # text before the first marker
        out.write(json.dumps({"page": n, "printed": pr, "text": re.sub(r"[ \t]{2,}", " ", text)},
                             ensure_ascii=False) + "\n")
print(f"{len(pages)} pages, printed {pages[0][0]}..{pages[-1][0]}")
