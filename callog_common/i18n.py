"""Multi-language — Turkish (primary) and English.

During visits from foreign auditors, the documents and the interface need to
appear in English. Since the text is embedded in the code, instead of
extracting everything into a translation file, **the source text itself is
the key**: `t("Sonuç")` returns the same text in Turkish, its counterpart in
English. This lets progress happen with almost no disruption to the existing
code, and text with no entry in the catalog silently stays in Turkish —
a partial translation, not a crash.

**The scope is deliberately limited, and this is a known gap, not a hidden one:**

* Certificate and report documents are **fully** translated — that's what
  ends up in the auditor's hands and gets kept.
* The navigation bar, menu bar, and page titles are translated.
* Most in-page hint text, warning dialogs, and button labels stay in Turkish.
  Translating those too would require extracting all of the text; that's a
  separate pass.

A language change takes effect **on restart**: the interface text is read
once when a widget is built, and rebuilding the entire window live would be
a much bigger change than what switching languages gains. Documents aren't
subject to this — they are written according to the active language at the
moment they're generated.

Doesn't know about Qt.
"""

from . import prefs

TR = "tr"
EN = "en"

LANGUAGES = ((TR, "Türkçe"), (EN, "English"))

_language = TR

#: Turkish source text -> English. If the key isn't found, the text is
#: returned as-is; so the catalog can be incomplete, but it can't be wrong.
CATALOG = {
    EN: {
        # --- certificate / report body ---------------------------------
        # The lab name now comes from the `branding` module and varies by
        # institution, so there's no fixed translation for it here.
        "KALİBRASYON SERTİFİKASI": "CALIBRATION CERTIFICATE",
        "Sertifika no": "Certificate no",
        "Veriliş tarihi": "Date of issue",
        "Ölçüm tarihi": "Date of measurement",
        "Ölçüm oturumu": "Measurement session",
        "Kalibre edilen cihaz": "Device under calibration",
        "Şirket / müşteri": "Company / customer",
        "Üretici firma": "Manufacturer",
        "Model": "Model",
        "Seri no": "Serial no",
        "Cihaz tipi": "Device type",
        "Kullanılan referans standart": "Reference standard used",
        "Cihaz": "Instrument",
        "Kalibrasyon sertifika no": "Calibration certificate no",
        "Geçerlilik": "Valid until",
        "Ortam şartları": "Environmental conditions",
        "Sıcaklık / nem / basınç": "Temperature / humidity / pressure",
        "elle girildi": "entered manually",
        "Ölçüm sonuçları": "Measurement results",
        "Ölçüm planı": "Measurement plan",
        "Ölçüm noktası %d — %s": "Measurement point %d — %s",
        "n = %d   ·   %s": "n = %d   ·   %s",
        "Ölçüm fonksiyonu": "Measurement function",
        "Ölçülen kanal": "Measured channel",
        "Okuma sayısı (n)": "Number of readings (n)",
        "%d  (dışlanan: %d)": "%d  (excluded: %d)",
        "Nominal değer": "Nominal value",
        "Tolerans": "Tolerance",
        "Uygunluk kriteri": "Conformity criterion",
        "Ölçülen ortalama": "Measured mean",
        "Standart sapma (s)": "Standard deviation (s)",
        "En küçük / en büyük": "Minimum / maximum",
        "Sapma": "Deviation",
        "Genişletilmiş belirsizlik U (k=2)": "Expanded uncertainty U (k=2)",
        "Sonuç": "Result",
        "Sonuç: %s": "Result: %s",
        "Ölçüm grafiği": "Measurement chart",
        "Ölçüm grafiği — %d. nokta, %s": "Measurement chart — point %d, %s",
        "Ölçümü yapan": "Measured by",
        "Onaylayan": "Approved by",
        "UYGUN": "PASS",
        "UYGUN DEĞİL": "FAIL",
        "BİLGİLENDİRME AMAÇLI": "FOR INFORMATION ONLY",
        "Ortalama ± U tolerans içinde": "Mean ± U within tolerance",
        "Tüm okumalar tolerans içinde": "All readings within tolerance",
        (
            "Beyan edilen genişletilmiş belirsizlik, standart belirsizliğin "
            "k=2 kapsam çarpanı ile çarpılmasıyla elde edilmiştir ve yaklaşık "
            "%95 kapsam olasılığına karşılık gelir. Bu sürümde yalnızca A tipi "
            "belirsizlik bileşeni hesaplanmaktadır; B tipi bileşenler "
            "eklendiğinde değer büyüyecektir."
        ): (
            "The reported expanded uncertainty is obtained by multiplying the "
            "standard uncertainty by a coverage factor k=2, corresponding to a "
            "coverage probability of approximately 95%. In this version only "
            "the Type A uncertainty component is evaluated; the value will "
            "increase once Type B components are included."
        ),
        (
            "SİMÜLASYON ÇIKTISI — GEÇERLİ SERTİFİKA DEĞİLDİR\n"
            "Bu belge simüle edilmiş bir cihazdan üretilmiştir. İçindeki ölçüm "
            "değerleri gerçek bir kalibrasyona ait değildir; yalnızca deneme ve "
            "eğitim amacıyla kullanılabilir."
        ): (
            "SIMULATED OUTPUT — NOT A VALID CERTIFICATE\n"
            "This document was produced from a simulated instrument. The "
            "measurement values it contains do not belong to a real "
            "calibration; it may be used for testing and training only."
        ),
        "SİMÜLASYON": "SIMULATED",
        "GEÇERLİ SERTİFİKA DEĞİLDİR": "NOT A VALID CERTIFICATE",

        # --- chart on the certificate ---------------------------------------
        "Süre (s)": "Time (s)",
        "● okuma": "● reading",
        "│ ±s (tek okuma)": "│ ±s (single reading)",
        "─ ortalama": "─ mean",
        "░ x̄ ± U (k=2)": "░ x̄ ± U (k=2)",
        "░ tolerans bandi": "░ tolerance band",
        "× dislanan (%d)": "× excluded (%d)",
        "Dagilim": "Distribution",

        # --- navigation and menus ----------------------------------------
        "Ana ekran": "Home",
        "Cihazlar": "Devices",
        "Yeni oturum": "New session",
        "Ölçüm": "Measurement",
        "Dalga yakalama": "Waveform capture",
        "Onay kuyruğu": "Approval queue",
        "Geçmiş kayıtlar": "History",
        "Yönetim": "Administration",
        "Oturum": "Session",
        "Görünüm": "View",
        "Yardım": "Help",
        "Yeni kalibrasyon oturumu": "New calibration session",
        "Oturumu bitir": "End session",
        "Ara…": "Search…",
        "Kalibre edilen cihazlar": "Calibrated devices",
        "Sertifikalar": "Certificates",
        "Çıkış": "Quit",
        "Beyaz tema": "Light theme",
        "Koyu tema": "Dark theme",
        "Yüksek kontrast": "High contrast",
        "Yazı boyutu": "Font size",
        "Yakınlaştır": "Zoom in",
        "Uzaklaştır": "Zoom out",
        "Yazı boyutunu sıfırla (%100)": "Reset zoom (100%)",
        "Dil / Language": "Dil / Language",
        "Kullanıcılar": "Users",
        "Referans cihazlar": "Reference instruments",
        "Yetki matrisi": "Permission matrix",
        "Denetim kaydı": "Audit log",
        "Denetim zincirini doğrula": "Verify audit chain",
        "Veritabanını yedekle": "Back up database",
        "Klavye kısayolları": "Keyboard shortcuts",
        "Hakkında": "About",

        # --- page titles -------------------------------------------
        "Kalibre edilen cihazlar defteri": "Calibrated device register",
        "Yeni kalibrasyon oturumu başlat": "Start a new calibration session",
    },
}


def set_language(code, user_id=None, persist=True):
    """Changes the language. Writes to the user's preference if `persist`."""
    global _language
    _language = code if code in dict(LANGUAGES) else TR
    if persist:
        prefs.set(user_id, prefs.LANGUAGE, _language)
    return _language


def load(user_id=None):
    """Loads and activates the user's saved language."""
    return set_language(prefs.get(user_id, prefs.LANGUAGE, TR), user_id,
                        persist=False)


def language():
    return _language


def label(code=None):
    return dict(LANGUAGES).get(code or _language, code or _language)


def t(text):
    """The source text's counterpart in the active language; the text itself if none."""
    if _language == TR or text is None:
        return text
    return CATALOG.get(_language, {}).get(text, text)
