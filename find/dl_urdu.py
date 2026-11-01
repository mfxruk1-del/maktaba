import json, urllib.request, urllib.parse, re, subprocess, pathlib, time
base = pathlib.Path.home() / "library" / "cand" / "urdu"
DI = {"bahar-shariat-1a": "2014/1172-1", "bahar-shariat-1b": "2014/1173-1", "bahar-shariat-2a": "2014/1174-1",
      "bahar-shariat-2b": "2014/1175-1", "bahar-shariat-3a": "2014/1176-1", "bahar-shariat-3b": "2014/1177-1"}
IA = [("amjadiyya", "FatawaAmjadia_Complete_201811", r"\.pdf$"),
      ("mustafawiyya", "FatawaMustafwiya", r"\.pdf$"),
      ("waqar", "WaqarUlFatawa_Complete", r"\.pdf$"),
      ("faqih-millat", "FatawaFaqihEMillat_Complete", r"\.pdf$"),
      ("imdad-jadid", "imdad-ul-fatawa-jadeed-Ashraf-Ali-Thanvi", r"\.pdf$"),
      ("kifayat-faruqia", "6_20260505_20260505_1150", r"\.pdf$")]
def get(url, dst, size=None):
    if dst.exists() and (size is None or dst.stat().st_size == int(size)) and dst.stat().st_size > 0:
        return
    for a in range(5):
        r = subprocess.run(["curl", "-sSLf", "-o", str(dst), url])
        if r.returncode == 0: print("ok", dst.name, flush=True); return
        time.sleep(20 * (a + 1))
    print("FAILED", dst.name, flush=True)
d = base / "bahar-shariat"; d.mkdir(parents=True, exist_ok=True)
for k, v in DI.items():
    get(f"https://data2.dawateislami.net/Data/Books/Download/ur/pdf/{v}.pdf", d / f"{k}.pdf")
for name, item, rx in IA:
    d = base / name; d.mkdir(parents=True, exist_ok=True)
    for f in json.load(urllib.request.urlopen(f"https://archive.org/metadata/{item}", timeout=60))["files"]:
        n = f["name"]
        if re.search(rx, n) and not n.endswith("_text.pdf"):
            get(f"https://archive.org/download/{item}/{urllib.parse.quote(n)}", d / n, f.get("size"))
print("DONE", flush=True)
