"""assemble.py <id> [<id>...] — rebuild ocr/<id>_ocr/{pages,<id>.jsonl} from ALL raw Kraken pages present
(VPS runs and remote workers alike) and render any missing scan images, so the edition can be indexed.
Same clean-up as ocr_book.sh step 3. Run from ~/library."""
import sys, json, re, unicodedata, pathlib, subprocess
swap = str.maketrans("()[]{}«»<>", ")(][}{»«><")
persian = str.maketrans({"ی": "ي", "ک": "ك"})
LTR = re.compile(r"[0-9٠-٩۰-۹](?:[0-9٠-٩۰-۹/.,:\-]*[0-9٠-٩۰-۹])?|[A-Za-z]+")
def fix_line(l):
    l = l[::-1].translate(swap)
    return LTR.sub(lambda m: m.group(0)[::-1], l)
for bid in sys.argv[1:]:
    out = pathlib.Path("ocr", f"{bid}_ocr"); raw = out / "raw"; pages = out / "pages"; img = out / "img"
    pages.mkdir(parents=True, exist_ok=True); img.mkdir(exist_ok=True)
    pdf = pathlib.Path("ocr", f"{bid}.pdf").resolve()
    nums = sorted(int(f.stem[1:]) for f in raw.glob("p*.txt") if f.stat().st_size > 0)
    rendered = 0
    with open(out / f"{bid}.jsonl", "w", encoding="utf-8") as js:
        for p in nums:
            lines = [unicodedata.normalize("NFC", fix_line(l)).translate(persian).strip()
                     for l in (raw / f"p{p:04d}.txt").read_text(encoding="utf-8").splitlines()]
            text = "\n".join(l for l in lines if l)
            (pages / f"p{p:04d}.txt").write_text(text + "\n", encoding="utf-8")
            js.write(json.dumps({"page": p, "text": text}, ensure_ascii=False) + "\n")
            png = img / f"p{p:04d}.png"
            if not png.exists():
                subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "300", "-gray", "-png", "-singlefile", str(pdf), str(png)[:-4]], check=True)
                rendered += 1
    print(bid, len(nums), "pages", (f"{nums[0]}-{nums[-1]}" if nums else ""), "rendered", rendered, flush=True)
