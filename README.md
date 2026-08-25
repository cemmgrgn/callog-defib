# CalLog Defib

Defibrilatör ve harici kalp pili dalga ölçümü, çözümlemesi ve
sertifikasyonu. Kalibrasyon laboratuvarları için ölçüm kayıt sistemi
**CalLog**'un iki uygulamasından biri — sertifika/denetim/kullanıcı
altyapısını [`callog-seshizi`](https://github.com/cemmgrgn/callog-seshizi)
(ses hızı / kalınlık ölçümü) ile paylaşır, ama tamamen bağımsız bir
kurulum ve depo: biri olmadan diğeri klonlanabilir, kurulabilir ve
çalıştırılabilir.

Geliştiren: **Cem Girgin**  ·  Lisans: [Özel Kullanım Lisansı](LICENSE)

Kurum adı, birim adı ve logo kaynak kodda gömülü değildir; kurulumdan
sonra Yönetim → Laboratuvar sayfasından girilir ve veritabanında saklanır
(bkz. [`callog_common/branding.py`](callog_common/branding.py)). Bu depo
hiçbir kuruma özgü bilgi içermez.

Uygulamayı ekran görüntüleriyle adım adım anlatan, tamamen jenerik bir
kullanım kılavuzu için: [`docs/kullanim-kilavuzu.pdf`](docs/kullanim-kilavuzu.pdf).
Ekran ekran davranış ve tasarım kararlarının gerekçesi için:
[`docs/REFERANS.md`](docs/REFERANS.md).

---

## Ne yapar

1. Kullanıcı kendi hesabıyla giriş yapar (kayıt kime ait — izlenebilirliğin temeli)
2. Kalibrasyona gelen cihazın (DUT) bilgileri elle girilir
3. Referans osiloskop otomatik tespit edilir (`*IDN?`) veya elle adres girilir
4. **Dalga yakalama** sayfasında tetikleme beklenir; şok/pacer darbesi CSV +
   ekran görüntüsü olarak kaydedilir
5. Faz süreleri, tepe gerilim/akım, eğim (tilt) ve yüke aktarılan enerji
   otomatik hesaplanır (`defib.py`, Qt'siz)
6. Tek şok, seri (n şok) ve toplu (tüm enerji kademeleri) PDF raporları üretilir
7. Her şey hash zinciriyle korunan denetim kaydına yazılır; geçmiş
   kayıtlarda arama, lab sorumlusu onayı, Excel'e aktarım

## Kurulum

Windows 10/11 + Python 3.12.

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

İlk açılışta kullanıcı olmadığı için yönetici hesabı oluşturma penceresi gelir.

**Cihaz olmadan denemek için:** referans cihaz listesinden
`[SİMÜLASYON] Keysight DSOX1202A` seçin. Simülasyon sürücüsü gerçekçi
bir bifazik şok dalgası üretir — akış gerçek cihaz olmadan test edilebilir.

Simülasyon oturumundan da sertifika üretilebilir, ancak çapraz
**SİMÜLASYON** filigranı taşır ve `SIM-` önekli ayrı bir seriden numara
alır — resmî sertifika numaralarını tüketmez.

## Dosya düzeni

```
callog_common/         Paylaşılan altyapı — bkz. aşağıdaki "Bağımlılık" bölümü
callog_defib/
├── defib.py            Şok/pacer çözümlemesi — Qt'siz
├── defib_modes.py       Test modlarını callog_common.testmodes'a kaydeder
├── shockreport.py        Tek şok raporu PDF
├── seriesreport.py       Seri (n şok) raporu PDF
├── summaryreport.py      Toplu değerlendirme raporu PDF (tüm kademeler)
└── ui/
    ├── main_window.py     callog_common'ın BaseMainWindow'unu genişletir
    └── waveform_page.py, waveform_capture.py, waveform_common.py,
        waveform_setup.py, waveform_results.py   Dalga yakalama sayfası
```

## Bağımlılık: `callog_common/`

Kullanıcı/rol yönetimi, sertifika üretimi, denetim kaydı, veritabanı
şeması, yedekleme, tema ve dil, ölçüm oturumu akışı gibi laboratuvar
altyapısının tamamı `callog_common/` altında — bu, aynı kodun
[`callog-seshizi`](https://github.com/cemmgrgn/callog-seshizi) deposunda
da **bir kopyası** olarak duruyor. Bu depoyu `callog-seshizi`'ye bağımlı
kılmamak için kopyalandı; canlı bir bağlantı değil.

**Bunun bedeli:** `callog_common`'da ileride bir hata düzeltilirse bu
depodaki kopya kendiliğinden güncellenmez — elle senkronize edilmeli
(`callog_common/` dizinini iki depo arasında kopyalayıp buradaki
`callog_defib`'e özgü hiçbir şeyi ezmediğinden emin olun).

`callog_common/ui/approvals_page.py` ve `devices_page.py`, `callog-defib`'e
özgü rapor kodunu (`seriesreport`, `summaryreport`) **isteğe bağlı** olarak
içe aktarır (`try/except ImportError`) — bu depoda her zaman bulunur,
`callog-seshizi`'de bulunmadığında ilgili ekran nazikçe "bu kurulumda
görüntülenemiyor" der.

## Test

```bash
python tests/smoke_test.py       # pyvisa/reportlab gerektirmez, ama PySide6 kurulu olmalı
python tests/gui_smoke_test.py   # ekransız (offscreen) çalışır
```

Windows'ta ekransız Qt platformu bazen sistem fontlarını bulamaz; bu durumda
her iki testten önce şunu ayarlayın:

```bash
set QT_QPA_FONTDIR=C:\Windows\Fonts
```

(`gui_smoke_test.py` `QT_QPA_PLATFORM=offscreen`'i kendi içinde ayarlar,
elle set etmeye gerek yok.)

`smoke_test.py`: 300/300. `gui_smoke_test.py`: 479/480 — kalan tek başarısızlık
(`kararlilik seridi en genis satir degil`), bu depoda hiç değiştirilmemiş
`acquire_page.py` kodunda, piksel genişliği karşılaştıran bir kontrol;
ekransız (offscreen) test ortamının font metrikleriyle ilgili görünüyor.
Gerçek ekranda ayrıca doğrulanmadı.

## Yeni cihaz eklemek

1. `callog_common/drivers/` altında `base.Driver`'ı miras alan bir modül yaz
2. `FUNCTIONS` listesini ve dört metodu doldur: `connect`, `close`, `configure`, `read_one`
3. `callog_common/drivers/__init__.py`'deki `REGISTRY`'ye ekle (uygulamaya
   özgü bir cihazsa `drivers.register_driver()` ile `callog_defib/__init__.py`'den)
4. Otomatik tespit için `discovery.KNOWN_MODELS`'e marka/model desenini ekle
