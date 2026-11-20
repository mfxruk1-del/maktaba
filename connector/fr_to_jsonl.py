"""Fatawa Ridawiyya (30-vol Urdu edition, Word -> .md) to Maktaba page records.

Usage: python fr_to_jsonl.py <dir with fr-vol-*.md> <out.jsonl>
There are no printed page numbers, so each record is a chunk of about TARGET characters, cut at
fatwa (مسئلہ) and heading boundaries where possible, and labelled in "printed" as
"vol · مسئلہ N · treatise/chapter" so it can be cited by volume, fatwa number and treatise.
"""
import json, pathlib, re, sys

TARGET, MIN_BREAK, HARD = 3000, 900, 4500
UDIG = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
MASALA = re.compile(r"^\**\s*مسئل[ہه]\s*([۰-۹0-9٠-٩]+(?:\s*(?:تا|-|–)\s*[۰-۹0-9٠-٩]+)?)")
BOLD = re.compile(r"^\*\*(.+?)\*\*")
RISALA_WORD = re.compile(r"^\(?\s*رس[ـ\s]*ا[ـ\s]*ل[ـ\s]*[ہه](\s*ضمنی[ہه])?\s*\)?$")
SENT = re.compile(r"(?<=[۔.؟?!÷:])\s+")


def vol_key(p):
    m = re.match(r"fr-vol-(\d+)([ab]?)\.md$", p.name)
    return (int(m.group(1)), m.group(2))


def clean_heading(h):
    h = re.sub(r"\*+", "", h).strip(" :()")
    return re.sub(r"\s+", " ", h)[:70]


def split_long(line):
    """Break a very long paragraph at sentence ends so no chunk is huge."""
    if len(line) <= HARD:
        return [line]
    out, cur = [], ""
    for s in SENT.split(line):
        if cur and len(cur) + len(s) > TARGET:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s) if cur else s
    if cur:
        out.append(cur)
    return out


def convert(src_dir, out_path):
    files = sorted(pathlib.Path(src_dir).glob("fr-vol-*.md"), key=vol_key)
    page, recs = 0, []
    for f in files:
        n, part = vol_key(f)
        vol = f"{n}{'-' + ('الف' if part == 'a' else 'ب') if part else ''}"
        kitab = bab = risala = ""
        masala = ""
        pending_risala = False
        buf, buf_label = [], None

        def label():
            ctx = risala or bab or kitab
            return " · ".join(x for x in (f"ج {vol}", f"مسئلہ {masala}" if masala else "", ctx) if x)

        def flush():
            nonlocal page, buf, buf_label
            text = "\n".join(buf).strip()
            if text:
                page += 1
                recs.append({"page": page, "printed": buf_label or label(), "text": text})
            buf, buf_label = [], None

        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            if not line.strip():
                continue
            size = sum(len(x) for x in buf)
            m_mas = MASALA.match(line)
            m_bold = BOLD.match(line.strip())
            boundary = bool(m_mas) or (bool(m_bold) and not m_bold.group(1).strip().startswith(("قال", "(")))
            if boundary and size >= MIN_BREAK:
                flush()
            # update context
            if m_mas:
                masala = m_mas.group(1).translate(UDIG).replace(" ", "").replace("تا", "–")
            for seg in (re.findall(r"\*\*(.+?)\*\*", line.strip()) if m_bold else []):
                h = clean_heading(seg)
                if not h:
                    continue
                if RISALA_WORD.match(h):
                    pending_risala = True
                elif h.startswith(("کتاب", "كتاب")):
                    kitab, bab, risala, masala = h, "", "", ""
                elif h.startswith("باب"):
                    bab, risala, masala = h, "", ""
                elif pending_risala or re.search(r"\([۰-۹0-9]{2}\s?[۰-۹0-9]{2}\s?ھ\)", h):
                    risala, pending_risala, masala = "رسالہ: " + re.sub(r"\(.*", "", h).strip(), False, ""
            if m_bold and all(x.lstrip().startswith("**") for x in buf):
                buf_label = None          # chunk so far is only headings: label it by the newest one
            for piece in split_long(line):
                if sum(len(x) for x in buf) + len(piece) > HARD and buf:
                    flush()
                if buf_label is None:
                    buf_label = label()   # label = context at the chunk's first line
                buf.append(piece)
                if sum(len(x) for x in buf) >= TARGET:
                    flush()
        flush()
        print(f"{f.name}: up to page {page}", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as o:
        for r in recs:
            o.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(recs)} records -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
