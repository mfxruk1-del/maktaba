"""Single source of truth for the library: works and their editions. Writes books.json.
Run: python3 catalog.py && (cd maktaba && ../maktaba-venv/bin/python build_index.py ..) && sudo systemctl restart maktaba
"""
import json, pathlib

TYPED = ("Digital text (not OCR): Shamela .bok from archive.org item {item}; the card says the page numbering matches "
         "the print, footnotes included. When scans are attached, 'page' is the scan's PDF page (get_page_image shows "
         "the printed page); otherwise a running number. Cite printed_page.")
OCR = ("OCR (Kraken + OpenITI Arabic model) of {scan}; diacritics dropped, ﷺ-type symbols garbled; "
       "verify quotes with get_page_image.")

KAWTHARI = "محمد زاهد الكوثري (ت 1371هـ)"
WORKS = [
  ("tanib", "تأنيب الخطيب على ما ساقه في ترجمة أبي حنيفة من الأكاذيب", KAWTHARI, [
    dict(id="tanib", primary=True, rating="Excellent", edition="الطبعة الجديدة 1410هـ / 1990م، بتعليقات أحمد خيري (الناشر غير مذكور في المسح)",
         source=OCR.format(scan="the archive.org scan 'Tanib_Alkhatib' (~99% word accuracy on tested pages)"),
         jsonl="Tanib_ocr/Tanib.jsonl", img="Tanib_ocr/img"),
  ]),
  ("fadail", "فضائل أبي حنيفة وأخباره ومناقبه", "ابن أبي العوام، أبو القاسم عبد الله بن محمد السعدي (ت 335هـ)", [
    dict(id="fadail", primary=True, digital=True,
         edition="تحقيق لطيف الرحمن البهرائجي القاسمي، المكتبة الإمدادية، مكة المكرمة، ط1 1431هـ / 2010م (392 ص، مع مقدمة المحقق)",
         source=TYPED.format(item="Fazail_Abi_Hanifa"), jsonl="texts/fadail.mapped.jsonl", img="scans/fadail"),
  ]),
  ("makki", "مناقب أبي حنيفة (الموفق المكي)", "الموفق بن أحمد المكي الخوارزمي (ت 568هـ)", [
    dict(id="makki", primary=True, digital=True,
         edition="دار الكتاب العربي، بيروت، ط5 1401هـ / 1981م (تصوير طبعة حيدرآباد 1321هـ)",
         source=TYPED.format(item="manaqib_abi_hanifa_202606"), jsonl="texts/makki.jsonl", img=None),
  ]),
  ("kardari", "مناقب أبي حنيفة (الكردري)", "حافظ الدين محمد بن محمد بن شهاب الكردري البزازي (ت 827هـ)", [
    dict(id="kardari", primary=True, digital=True,
         edition="دار الكتاب العربي، بيروت، ط5 1401هـ / 1981م (تصوير طبعة حيدرآباد 1321هـ)",
         source=TYPED.format(item="manaqib_abi_hanifa_20260620"), jsonl="texts/kardari.jsonl", img=None),
  ]),
  ("uqud", "عقود الجمان في مناقب الإمام الأعظم أبي حنيفة النعمان", "محمد بن يوسف الصالحي الشامي (ت 942هـ)", [
    dict(id="uqud", primary=True, digital=True,
         edition="لجنة إحياء المعارف النعمانية، حيدرآباد الدكن، ط1 1394هـ / 1974م (صورتها مكتبة الإيمان بالمدينة)",
         source=TYPED.format(item="Uqud_Al-juman"), jsonl="texts/uqud.mapped.jsonl", img="scans/uqud"),
  ]),
  ("khayrat", "الخيرات الحسان في مناقب الإمام الأعظم أبي حنيفة النعمان", "ابن حجر الهيتمي (ت 974هـ)", [
    dict(id="khayrat", primary=True, digital=True,
         edition="تحقيق محمد عاشق إلهي البرني المدني، مطبعة المدني، القاهرة، ط1 1415هـ / 1994م (248 ص)",
         source=TYPED.format(item="al-khayrat_al-hisan_202606"), jsonl="texts/khayrat.jsonl", img=None),
    dict(id="khayrat-huda", digital=True,
         edition="تحقيق عبد الكريم موسى المحيميد، دار الهدى والرشاد، دمشق، ط1 1428هـ / 2007م (192 ص)",
         source=TYPED.format(item="al-khayrat_al-hisan_20260625"), jsonl="texts/khayrat-huda.mapped.jsonl", img="scans/khayrat-huda"),
  ]),
  ("tabyid", "تبييض الصحيفة في مناقب الإمام أبي حنيفة", "جلال الدين السيوطي (ت 911هـ)", [
    dict(id="tabyid-arqam", primary=True, digital=True,
         edition="تحقيق محمد عاشق إلهي البرني، دار الأرقم بن أبي الأرقم، بيروت، ط1 1424هـ / 2003م (158 ص، بتعليقات موسعة)",
         source=TYPED.format(item="Tabiizus_Sahifa_Fi_Manaqib_Al-Imam_Abu_Hanifa"), jsonl="texts/tabyid-arqam.mapped.jsonl", img="scans/tabyid-arqam"),
    dict(id="tabyid", digital=True,
         edition="تحقيق هيئة التحقيق بدار الوعي العربي، حلب، ط1 1428هـ / 2007م (48 ص)",
         source=TYPED.format(item="tabiizus_sahifa_fi_manaqib_al-imam_abu_hanifa_202606"), jsonl="texts/tabyid.jsonl", img=None),
  ]),
  ("dinawari", "مناقب أبي حنيفة (أبو الحسن الدينوري)", "أبو الحسن علي بن محمد الدينوري اللبان (ت 468 أو 469هـ)", [
    dict(id="dinawari-2025", primary=True, digital=True,
         edition="تحقيق سيد كليم الله حرمزئي، دار الفتح، عمان، ط1 1446هـ / 2025م (264 ص، عن نسخة مغنيسيا مع مقابلة نسخة ثانية؛ أفاد من تحقيق كوتوك)",
         source=TYPED.format(item="manaqib_abi_hanifa_20260623"), jsonl="texts/imam-aimma.jsonl", img=None),
    dict(id="dinawari-2020", digital=True,
         edition="تحقيق شعبان كوتوك (ونادي فتحي مجلي)، مجلة Tahkik، إسطنبول، م3 ع6 ديسمبر 2020م؛ يقابل عدة نسخ خطية (م، ب، ك)",
         source=TYPED.format(item="Manaqib_Abi_Hanifa"), jsonl="texts/dinawari.jsonl", img=None),
  ]),
  ("zaranjari", "مناقب أبي حنيفة (الزرنجري)", "القاضي أبو الفضل بكر بن محمد الزرنجري (ت 512هـ)", [
    dict(id="zaranjari-hanbali", primary=True, digital=True,
         edition="تحقيق محمد وائل الحنبلي، دار السمان، إسطنبول، ط1 1442هـ / 2021م (250 ص، رواية علي بن محمد البلخي)",
         source=TYPED.format(item="manaqib_abi_hanifa_20260623_1104"), jsonl="texts/zaranjari-hanbali.mapped.jsonl", img="scans/zaranjari-hanbali"),
    dict(id="zaranjari", digital=True,
         edition="تحقيق مراد شيمشيك وشعبان كوتوك، مجلة Tahkik، إسطنبول، م1 ع1 يونيو 2018م (صفحات المجلة 67-162)",
         source=TYPED.format(item="manaqib_abi_hanifa_20260622"), jsonl="texts/zaranjari.jsonl", img=None),
  ]),
  ("fiqh-iraq", "فقه أهل العراق وحديثهم", KAWTHARI, [
    dict(id="fiqh-iraq", rating="Fair",
         edition="نشرة مستقلة لمقدمة الكوثري على نصب الراية (archive.org Elkawthari/fiqh3iraq.pdf)",
         source=OCR.format(scan="archive.org Elkawthari/fiqh3iraq.pdf (300 dpi, 1-bit)")
                + " WEAKER OCR (~90% words; no printed page numbers detected, cite PDF page). Clean typed text: al-Kawthari's "
                  "introduction in Shamela's Nasb al-Raya (book 11428) - quote from there.",
         jsonl="ocr/fiqh_ocr/fiqh.jsonl", img="ocr/fiqh_ocr/img"),
  ]),
  ("maqalat", "مقالات الكوثري", KAWTHARI, [
    dict(id="maqalat", primary=True, rating="Good", edition="المكتبة التوفيقية، القاهرة (561 ص في المسح)",
         source=OCR.format(scan="archive.org Elkawthari/maqalaate.pdf (low-resolution 72-dpi scan: ~95% word accuracy)"),
         jsonl="ocr/maqalat_ocr/maqalat.jsonl", img="ocr/maqalat_ocr/img"),
  ]),
  ("kashf", "كشف الآثار الشريفة في مناقب الإمام أبي حنيفة", "أبو محمد عبد الله بن محمد الحارثي البخاري (ت 340هـ)", [
    dict(id="kashf", primary=True, digital=True,
         edition="تحقيق لطيف الرحمن البهرائجي القاسمي، مكتبة الإرشاد، إسطنبول، ط1 1441هـ / 2020م، مجلدان",
         source=TYPED.format(item="Kashf_Al-Asar") + " Pages are numbered as the PDF pages of the usul.ai scan of the same "
                "edition, so get_page_image shows the printed page (vol 1: pdf = printed + 1; vol 2: pdf = printed + 625).",
         jsonl="texts/kashf-bok.mapped.jsonl", img="ocr/kashf_ocr/img"),
  ]),
  ("fatawa-ridawiyya", "العطايا النبوية في الفتاوى الرضوية (فتاوى رضويه)", "الإمام أحمد رضا خان البريلوي (ت 1340هـ)", [
    dict(id="fatawa-ridawiyya", primary=True, digital=True,
         edition="الطبعة الأردية في 30 مجلدًا (المجلد الأول في جزأين)، مع ترجمة النصوص العربية والفارسية إلى الأردية، والأصل العربي محفوظ بجانبها (يرجح أنها طبعة رضا فاؤنڈیشن، لاہور)",
         source="Digital text from the user's Word files (converted to .md); Urdu with the Arabic originals. NO PRINTED PAGE NUMBERS: "
                "'page' is a running chunk number (~3,000 characters) and printed_page is a label 'ج <volume> · مسئلہ <fatwa no.> · <treatise or chapter>'. "
                "Cite as Fatawa Ridawiyya, vol., masala number and treatise; Urdu marked (ت) is the editors' translation, not Imam Ahmad Rida's own words.",
         jsonl="texts/fatawa-ridawiyya.jsonl", img=None),
  ]),
]

# ---- editions OCR'd on 25 Oct 2026 (VPS + Colab); ratings from scan checks + word score
EXTRA = {
  "maqalat": [dict(id="maqalat-bannuri", rating="Good",
      edition="طبعة مزيدة ومنقحة، بمقدمة الشيخ محمد يوسف البنوري (الناشر غير مقروء في المسح؛ 640 ص)",
      source=OCR.format(scan="archive.org AAskZad-1105906 (366-dpi scan, but the text block is small on the page: ~92% words)") + " Printed page numbers may be off by one in places: check the number on the scan before citing.",
      jsonl="ocr/maqalat-bannuri_ocr/maqalat-bannuri.jsonl", img="ocr/maqalat-bannuri_ocr/img")],
  "fiqh-iraq": [dict(id="fiqh-azhariyya", primary=True, rating="Excellent",
      edition="نشرة مستقلة، القاهرة (الناشر بجوار الجامع الأزهر، درب الأتراك؛ يرجح أنها المكتبة الأزهرية للتراث)، ط1، رقم الإيداع 2009",
      source=OCR.format(scan="archive.org Pdf4157 (439-dpi scan)"),
      jsonl="ocr/fiqh-azhariyya_ocr/fiqh-azhariyya.jsonl", img="ocr/fiqh-azhariyya_ocr/img")],
  "uqud": [dict(id="uqud-thesis", rating="Fair",
      edition="تحقيق ودراسة مولوي محمد ملا عبد القادر الأفغاني، رسالة ماجستير، جامعة الملك عبد العزيز (كلية الشريعة، فرع الكتاب والسنة)، إشراف د. أحمد فهمي أبو سنة؛ نسخة مرقونة على الآلة الكاتبة",
      source=OCR.format(scan="archive.org Oqoudjomane (300-dpi scan of the typescript thesis)") + " Typewriter text: ~88-90% words, NARRATOR NAMES OFTEN MISREAD (e.g. طلحة بن مصرف -> الحة بن صرف); always read names from the scan.",
      jsonl="ocr/uqud-thesis_ocr/uqud-thesis.jsonl", img="ocr/uqud-thesis_ocr/img")],
  "khayrat": [dict(id="khayrat-1324", rating="Fair",
      edition="طبع على نفقة مولوي محمد عبد الله وشركائه في بومباي، بمطبعة السعادة بمصر، 1324هـ",
      source=OCR.format(scan="archive.org 0102461324 (low-resolution 140-dpi scan of the old print)"),
      jsonl="ocr/khayrat-1324_ocr/khayrat-1324.jsonl", img="ocr/khayrat-1324_ocr/img")],
  "tabyid": [dict(id="tabyid-ilmiyya", rating="Fair",
      edition="تحقيق محمد محمود (خريج دار العلوم)، دار الكتب العلمية، بيروت، ط1 (اسم المحقق كاملًا غير مقروء في المسح)",
      source=OCR.format(scan="archive.org TabyidSahifa (low-resolution 126-dpi scan)"),
      jsonl="ocr/tabyid-hyd_ocr/tabyid-hyd.jsonl", img="ocr/tabyid-hyd_ocr/img")],
}

# ---- large Hanafi fatawa/furu' works (added 31 Oct 2026). One edition entry per VOLUME (id <work>-<vol>);
# full-volume OCR is still running (VPS + Kaggle workers), so a volume is listed only once some pages are OCR'd,
# and its source note says how many pages are in so far. Search the work id to cover every volume.
def _vols(work, n, fmt, edition, scan, rating):
    out = []
    for v in range(1, n + 1):
        vid = fmt.format(v)
        js = pathlib.Path(__file__).parent / f"ocr/{vid}_ocr/{vid}.jsonl"
        if not js.exists():
            continue
        done = sum(1 for _ in open(js, encoding="utf-8"))
        out.append(dict(id=vid, primary=(v == 1), rating=rating, edition=f"{edition} — ج {v}",
            source=OCR.format(scan=scan.format(v=v)) + f" PARTIAL: {done} pages of this volume OCR'd so far; 'page' is the PDF page.",
            jsonl=f"ocr/{vid}_ocr/{vid}.jsonl", img=f"ocr/{vid}_ocr/img"))
    return out
WORKS += [
  ("tatarkhaniyya", "الفتاوى التاتارخانية", "عالم بن العلاء الأنصاري الأندربتي الدهلوي الهندي (ت 786هـ)",
   _vols("tatarkhaniyya", 20, "tatarkhaniyya-{:02d}",
     "تحقيق وترقيم وتخريج المفتي شبير أحمد القاسمي (الجامعة القاسمية، مدرسة شاهي، مراد آباد)، 20 مجلدًا، مع تخريج نحو عشرة آلاف حديث وأثر؛ طبعة مكتبة زكريا، ديوبند (اسم الناشر غير مقروء في صفحة العنوان)",
     "archive.org Fatawatatarkhania file Fattatar{v:02d}.pdf (born-digital PDF whose text layer uses a legacy font encoding, so it was rendered at 300 dpi and OCR'd; ~97-99% words on checked pages). 'م:' in the text = al-Muhit al-Burhani, 'التجريد' etc. are al-Tatarkhaniyya's own source sigla; the numbered hadith paragraphs are the editor's takhrij",
     "Good")),
  ("dhakhira", "الذخيرة البرهانية (ذخيرة الفتاوى)", "برهان الدين محمود بن أحمد ابن مازة المرغيناني البخاري (ت 616هـ)",
   _vols("dhakhira", 15, "dhakhira-{:02d}",
     "تحقيق د. أبو أحمد العادلي، إبراهيم محمد سليم، أسامة كمال عبيد، عربي إبراهيم عبد الله، فهيم السيد فهيم التحيوي، صابر يوسف طعيمة؛ دار الكتب العلمية، بيروت، ط1 1440هـ / 2019م، 15 جزءًا",
     "archive.org 15_20200929_202009 file {v:02d}.pdf (300-dpi render). Footnotes 'في م / في أ' are the editors' manuscript variants",
     "Good")),
  ("muhit-radawi", "المحيط الرضوي", "رضي الدين محمد بن محمد السرخسي (ت 571هـ)",
   _vols("muhit-radawi", 9, "muhit-radawi-{}",
     "تحقيق عبد الحفيظ محمد علي بيضون، 9 مجلدات (نُقد التحقيق بكثرة التصحيف: قارن بالمخطوط أو بالنقول عند الشك)",
     "archive.org 20250905_20250905_1028 volume {v} (300-dpi render)",
     "Fair")),
]
WORKS = [(w, t, a, eds + EXTRA.get(w, [])) for w, t, a, eds in WORKS]

books = []
for wid, wtitle, author, eds in WORKS:
    for e in eds:
        e = dict(e)
        books.append({"id": e.pop("id"), "work": wid, "work_title": wtitle, "title": wtitle, "author": author, **e})
root = pathlib.Path(__file__).parent
missing = [b["jsonl"] for b in books if not (root / b["jsonl"]).exists()]
if missing:
    raise SystemExit(f"missing files: {missing}")
(root / "books.json").write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(WORKS)} works, {len(books)} editions -> books.json")
