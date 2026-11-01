"""Download Shamela .bok books from archive.org (served from inside their .rar) and convert them to jsonl."""
import subprocess, urllib.parse, pathlib, sys
BOOKS = {  # id: (archive.org item, rar name, bok name or None = find it in the rar listing)
    "fadail-bok": ("Fazail_Abi_Hanifa", "فضائل أبي حنيفة وأخباره ومناقبه.rar", None),
    "kashf-bok": ("Kashf_Al-Asar", "كشف الآثار الشريفة في مناقب الإمام أبي حنيفة.rar", None),
    "khayrat-huda": ("al-khayrat_al-hisan_20260625", "الخيرات الحسان في مناقب الإمام الأعظم أبي حنيفة النعمان - ط الهدى.rar", None),
    "tabyid-arqam": ("Tabiizus_Sahifa_Fi_Manaqib_Al-Imam_Abu_Hanifa", "تبييض الصحيفة في مناقب الإمام أبي حنيفة النعمان.rar", None),
    "zaranjari-hanbali": ("manaqib_abi_hanifa_20260623_1104", "مناقب الإمام أبي حنيفة للزرنجري.rar", None),
    "kardari": ("manaqib_abi_hanifa_20260620", "مناقب أبي حنيفة للكردري.rar", "مناقب أبي حنيفة للكردري.bok"),
    "makki":   ("manaqib_abi_hanifa_202606", "مناقب أبي حنيفة للموفق المكي.rar", "مناقب أبي حنيفة للموفق المكي.bok"),
    "uqud":    ("Uqud_Al-juman", "عقود الجمان في مناقب الإمام الأعظم أبي حنيفة النعمان.rar", "عقود الجمان في مناقب الإمام الأعظم أبي حنيفة النعمان.bok"),
    "tabyid":  ("tabiizus_sahifa_fi_manaqib_al-imam_abu_hanifa_202606", "تبييض الصحيفة في مناقب الإمام أبي حنيفة - ط الوعي.rar", "تبييض الصحيفة في مناقب الإمام أبي حنيفة - ط الوعي.bok"),
    "khayrat": ("al-khayrat_al-hisan_202606", "الخيرات الحسان في مناقب الإمام الأعظم أبي حنيفة النعمان - ط المدني.rar", "الخيرات الحسان في مناقب الإمام الأعظم أبي حنيفة النعمان - ط المدني.bok"),
}
root = pathlib.Path.home() / "library" / "texts"
root.mkdir(exist_ok=True)
q = urllib.parse.quote
for bid, (item, rar, bok) in BOOKS.items():
    dst = root / f"{bid}.bok"
    if not dst.exists():
        if bok is None:   # read the .bok name from archive.org's listing of the rar
            import re, urllib.request
            listing = urllib.request.urlopen(f"https://archive.org/download/{item}/{q(rar)}/", timeout=60).read().decode("utf-8", "replace")
            bok = urllib.parse.unquote(re.findall(r'href="[^"]*/([^"/]+\.bok)"', listing)[0])
        url = f"https://archive.org/download/{item}/{q(rar)}/{q(bok)}"
        subprocess.run(["curl", "-sSLf", "-o", str(dst), url], check=True)
    print(f"##### {bid}")
    subprocess.run([sys.executable, str(pathlib.Path.home() / "library/maktaba/bok_to_jsonl.py"),
                    str(dst), str(root / f"{bid}.jsonl")], check=True)
