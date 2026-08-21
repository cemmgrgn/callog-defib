# Referans — CalLog

Bu dosya README'nin kısa tutulması için ayrıldı: ekran ekran davranış,
tasarım kararlarının gerekçesi ve test kapsamının tam dökümü burada.
Kurulum / hızlı başlangıç için [`README.md`](../README.md)'ye bakın.

---

## Arayüz

**Sol gezinme şeridi:** Ana ekran · Cihazlar · Yeni oturum · Ölçüm ·
Dalga yakalama · Onay kuyruğu · Geçmiş kayıtlar · Yönetim. Ölçüm yalnızca bir
oturum başlatıldığında etkinleşir; Onay kuyruğu yalnızca sertifika onaylayabilenlerde.
Şeridin altında kim olarak girildiği, rol rozeti, tema düğmesi ve çıkış durur —
yanlış hesapla ölçüm kaydetmek geri alınamadığı için bu bilgi sürekli görünür.

Sekme çubuğu yerine şerit: etiketler uzun ("Kalibre edilen cihazlar"), sayfa
sayısı role göre değişiyor ve yatay çubukta eksik bir sekme fark ediliyor.

**Menü çubuğu kategorilere ayrılmış:** Oturum · Görünüm · Yönetim · Yardım.
Yönetim menüsü yalnızca yetkisi olanda görünür. Kısayollar: `Ctrl+N` yeni oturum,
`Ctrl+K` genel arama, `Ctrl+D` cihazlar, `Ctrl+H` geçmiş, `Ctrl+O` onay kuyruğu,
`Ctrl+B` veritabanı yedeği, `Ctrl+1..8` sayfalar, `F1` kısayol listesi. Sayfa numaraları **şeritte
görünen** sırayla aynı: rol yüzünden eklenmemiş bir sayfa numara tüketmiyor.

**Ana ekranda bildirim kutusu:** onay bekleyen sertifika, kalibrasyon
geçerliliği dolmuş ya da dolmak üzere olan referans cihaz, dosyası kaybolmuş
belge, son 24 saatteki başarısız girişler ve eskimiş veritabanı yedeği tek
listede toplanır — bu beş bilgi daha önce beş ayrı ekrandaydı. Satıra çift
tıklamak ilgili sayfayı açar. Bildirim yoksa kutu **hiç görünmez**: sürekli
duran boş bir "her şey yolunda" paneli birkaç gün içinde görünmez oluyor ve
dolduğunda da fark edilmiyor. Liste yetkiye göre budanır — operatöre müdahale
edemeyeceği onay kuyruğu gösterilmez.

**Hedef ekran: 1920×1080, pencereli tam ekran.** Görev çubuğu, pencere
çerçevesi, menü ve durum çubuğu düşüldükten sonra gövdeye ~1000 piksel
yükseklik kalıyor ve yerleşim buna göre ayarlandı: yazı 12 px, giriş kutusu
28 px, tablo satırı yazı ölçüsünden hesaplanıyor (12 px yazıda 24 px). Sayfa
kenar boşluğu ve aralıklar `util.PAGE_MARGIN` / `PAGE_SPACING` ile ortak.

Pencerenin en dar çizilebileceği ölçü **1612 × 609 piksel**. Yükseklik
sınırının düşük olması önemli: Qt, sığmayan bir düzende widget'ları en az
boyutlarının **altına** sıkıştırıyor ve metin kutuların içinde kırpılıyor.
Uzun sayfalar (Yeni oturum) bu yüzden kaydırılabilir — sığmayan içerik
sıkıştırılmıyor, kaydırılıyor.

**Boş durumlar** açıklama yazar ("Kayıtlı cihaz yok. 'Yeni cihaz ekle' ile
başlayın ya da ilk ölçüm oturumu açıldığında cihaz otomatik eklenir.") — boş bir
tablo tek başına arızayla kullanım hatasını ayırt ettirmiyor.

**Tema:** varsayılan beyaz. İşletim sisteminin tema ayarı takip edilmez —
laboratuvar PC'lerinin ayarları farklı ve ölçüm ekranının her makinede aynı
görünmesi isteniyor. Görünüm menüsünde üç palet var: beyaz, koyu ve **yüksek
kontrast**.

**Yüksek kontrast**, açık temanın kontrastı artırılmış hâli değil, ayrı bir
palet: gri tonlar tamamen kaldırılmış (soluk metin de tam siyah), kenarlıklar
koyu, ızgara belirgin. Lab ekranları küçük ve çoğu zaman uzaktan okunuyor;
normal temadaki gri metin ve ince çizgiler o mesafede kayboluyor.

**Yazı boyutu** Görünüm → Yazı boyutu'ndan %90 ile %150 arasında
ayarlanıyor. Tek bir çarpan stil sayfasındaki bütün `font-size` değerlerini
yeniden yazıyor; boyutları tek tek ayarlamak yerine bu, başlık / gövde / ipucu
oranlarının bozulmamasını garanti ediyor. Çarpan 1.0'da metin hiç dokunulmadan
geçiyor, yani varsayılan görünüm birebir korunuyor.

**Tercihler kullanıcıya bağlı.** Tema, yazı boyutu ve dil `QSettings` ile
**makineye** yazılıyordu; paylaşılan lab PC'sinde kullanıcılar birbirinin
ayarını değiştiriyordu. Artık `user_prefs` tablosunda tutuluyor ve giriş
yapıldığı anda o kullanıcının ayarı uygulanıyor. Giriş ekranında henüz
bağlanacak bir hesap olmadığı için orada hâlâ makine ayarı geçerli.

Tercihler denetim kaydına yazılmıyor: bir görünüm ayarının izlenebilirlikle
ilgisi yok ve her tema değişimi zinciri şişirirdi.

### Çoklu dil (TR / EN)

Görünüm → Dil / Language. Kaynak metnin kendisi anahtar (`t("Sonuç")`), ayrı
bir çeviri dosyası yok: katalogda karşılığı olmayan bir metin sessizce Türkçe
kalıyor — yarım çeviri, çökme değil.

**Kapsam bilinçli olarak sınırlı ve bu bir eksik, gizlenmiyor:**

| Kapsam | Durum |
|---|---|
| Sertifika ve rapor belgeleri (PDF + DOCX) | **tam çevrili** |
| Gezinme şeridi, menü çubuğu | çevrili |
| Sayfa içi ipuçları, uyarı pencereleri, düğme yazıları | Türkçe kalıyor |

Belgenin tam çevrili olması bilinçli önceliklendirme: denetçinin eline geçen ve
saklanan şey o. Arayüzün geri kalanını çevirmek metinlerin tamamının
ayıklanmasını gerektiriyor; ayrı bir tur.

Dil değişikliği **yeniden başlatmada** geçerli oluyor — arayüz metinleri widget
kurulurken bir kez okunuyor ve tüm pencereyi canlı yeniden kurmak, dil
değiştirmenin kazandırdığından çok daha büyük bir değişiklik. Belgeler buna
tabi değil: üretildikleri anda geçerli dile göre yazılıyorlar.

**Türkçe karakter desteği:** arayüzün tamamı ve PDF sertifika. reportlab'ın
yerleşik Helvetica fontu ş/ğ/İ/ı karakterlerini içermediği için PDF'e Unicode bir
TTF gömülür (`pdffont.py`; DejaVu Sans → Segoe UI → Arial → Tahoma sırasıyla
denenir ve Türkçe karakterlerin varlığı doğrulanır).

## Ölçüm planı (çoklu ölçüm noktası)

Bir oturum = bir nokta değil artık. Bir multimetre 10 V, 100 V, 1 kΩ, 100 kΩ
gibi 6–12 noktada kalibre ediliyor; her nokta için ayrı oturum açmak aynı
cihazı, aynı referansı ve aynı ortam şartlarını on kez yeniden girmek ve on
ayrı sertifika üretmek demekti.

**Yeni oturum → Ölçüm planı**: yukarıdaki fonksiyon / nominal / tolerans /
kriter değerleri "Noktayı plana ekle" ile listeye giriyor; sıra ok tuşlarıyla
değiştirilebiliyor. **Plan boş bırakılabilir** — o zaman formdaki değerler tek
noktalık bir plan oluşturuyor ve akış bugüne kadarki haliyle aynı kalıyor. Tek
nokta ölçen operatörü plan kurmaya zorlamak, kazandırdığından fazlasını
götürürdü.

**Ölçüm ekranında** solda plan paneli duruyor (tek noktalı oturumda hiç
görünmüyor): sıra, nokta, o noktada biriken okuma sayısı, durum. "Sonraki
nokta" bulunduğu noktayı kapatıp sıradakine geçiyor, cihazı yeni fonksiyona
ayarlıyor, istatistiği ve uyarıları sıfırlıyor. Kaynağı yeni değere ayarlamak
operatörün işi olduğu için kayıt kendiliğinden başlamıyor.

Cihazın yeniden ayarlanması **okuma iş parçacığına havale ediliyor**
(`AcquisitionWorker.request_configure`). `driver.configure()` doğrudan ana iş
parçacığından çağrılsaydı, okuma döngüsü tam o sırada `read_one()` içindeyken
aynı VISA oturumuna iki yerden yazılırdı.

**Sertifikada** her nokta kendi bölümünü alıyor — kendi nominali, toleransı,
kriteri, ortalaması, belirsizliği ve grafiği. Üstte bir plan özeti tablosu
hangi noktanın ne sonuç verdiğini bir bakışta gösteriyor. **Bir nokta bile
uygun değilse belge uygun değildir**: sertifika cihazın o noktalarda
kullanılabilir olduğunu söylüyor, noktaların ortalamasını değil.

### Geriye dönük uyum

İki kural, mevcut veriye hiç dokunmadan çalışmayı sürdürmeyi sağlıyor:

* `sessions` tablosundaki fonksiyon / nominal / tolerans sütunları **duruyor**
  ve planın ilk noktasını yansıtıyor. Geçmiş listesi, seyir grafiği ve dalga
  sorguları değişmeden çalışıyor.
* `readings.point_id` **NULL ise okuma ilk noktaya aittir**. Eski okumaları
  doldurmak `UPDATE` gerektirirdi ve `readings` üzerindeki tetikleyici buna
  izin vermiyor — vermemeli de.

Planı olmayan eski bir oturum ilk kez açıldığında kendi sütunlarından tek
noktalı bir plan kuruluyor (`points.ensure_default`). Bu **açıkça** çağrılıyor,
liste okumanın içine gizlenmiyor: bir okuma çağrısının sessizce veritabanına
yazması, izi zor sürülen bir davranış olurdu.

### Ölçüm şablonları

"Fluke 175 · yıllık kalibrasyon" gibi hazır kalıp: nokta planı, okuma periyodu
ve NPLC birlikte saklanıyor, yeni oturumda tek tıkla uygulanıyor. **Elle
girilen tolerans en olası veri giriş hatası** — bir kez doğru girilip
kaydedilmesi, her oturumda yeniden yazılmasından güvenli.

Şablon adı benzersiz; aynı adla kaydetmek üzerine yazıyor. Şablon ölçüm verisi
değil, bir form doldurma kısayolu: yumuşak silme yok, silinince gerçekten
siliniyor. Şablondan üretilmiş oturumlar etkilenmiyor — plan oturuma
**kopyalanıyor**, bağ kurulmuyor. Bağ kurulsaydı şablonun sonradan değişmesi
geçmiş bir sertifikanın planını değiştirmiş gibi görünürdü.

Seçili referans cihaza uymayan fonksiyonlar şablon uygulanırken atlanıyor ve
hangileri olduğu söyleniyor; sessizce yüklemek "başlat"ta anlaşılmaz bir
hataya dönüşürdü.

## Ölçüm ekranı

X ekseni **geçen süre (saniye)** — monotonik saatten ölçülür, sistem saati
oturum ortasında değişse bile grafik bozulmaz.

Başlıkta operatörün girdiği **hedef** görünür: nominal değer, ± tolerans, bandın
alt/üst sınırı ve uygunluk kriteri.

İstatistik paneli: anlık · n · ortalama · std sapma · u(A tipi) · en küçük ·
en büyük · sapma · uygunluk kararı.

"Sertifikasyonu başlat"a basıldıktan sonra düğme **"Sertifikasyon sürüyor"**a
döner ve rozet KAYIT olur; oturum bitince ikisi de geri döner.

Aykırı değer dışlama **çoklu seçimi** destekler: Ctrl/Shift ile birden fazla
satır seçilip tek gerekçeyle dışlanır (tek denetim kaydı yazılır). Tabloda
**sağ tık menüsü** var: dışla · dışlamayı kaldır · panoya kopyala. Dışlamanın
geri alınması da gerekçeli ve denetim kaydına `reading.include` olarak geçiyor.

Grafik kontrolleri:

| Kontrol | İşlevi |
|---|---|
| Pencere | Son 10 sn / 30 sn / 1 dk / 5 dk / 15 dk / Tümü / Yakınlaştırmayı koru |
| Takip et | Grafik en son okumayı izlemeye devam eder |
| Y otomatik | Y ekseni veriye göre ölçeklenir; kapatınca elle yapılan ölçek korunur |
| Izgara | Izgara çizgileri |
| Tolerans bantları | Nominal ve ± tolerans çizgileri |
| Grafiği kaydet | Görünen grafiği PNG ya da SVG olarak diske yazar |
| Görünümü sıfırla | Takip + otomatik ölçeğe döner |

**Yakınlaştırdıktan sonra da kayar:** zaman penceresi "Yakınlaştırmayı koru"
seçiliyken mevcut görünüm genişliği korunur ve pencere veriyle birlikte ilerler.

### Kararlılık göstergesi ve otomatik durdurma

"Okuma oturdu mu" kararı göz kararı verildiği sürece aynı ölçüm iki operatörde
iki farklı sürüyor. Gösterge son **20 okumaya** bakıp dört durumdan birini
söylüyor (`stability.py`, Qt'siz ve ayrıca test ediliyor):

| Durum | Koşul | Anlamı |
|---|---|---|
| veri toplanıyor | n < 5 | karar verilmiyor |
| oturuyor | \|birikim\| > 2s | pencere boyunca yönlü değişim gürültünün üstünde |
| saçılım geniş | yayılım > tolerans | okumalar bandın kendisinden geniş saçılıyor |
| kararlı | kalanı | — |

Yönlü birikime bakılmasının nedeni: yalnızca saçılıma bakılsaydı, gürültüsüz
ama sürekli tırmanan bir okuma "dar saçılım" görünürdü.

Gösterge **izleme modunda da** çalışıyor — "kaydı ne zaman başlatayım"
sorusunun cevabı da bu.

**Durdurma koşulu** iki türlü verilebilir: *hedef okuma sayısı* (ilerleme
çubuğu ne kadar kaldığını gösterir) ya da *kararlı olunca durdur*. Koşul
sağlandığında **yalnızca kayıt durur, oturum kapanmaz**: aksi halde ekran
operatör sonucu görmeden değişir, aykırı bir okumayı dışlama fırsatı kalmazdı.
Durdurulmuş kayıt yeniden başlatılamıyor — aynı oturumda ikinci bir kayıt turu
ilkinin okumalarıyla aynı sertifikaya girerdi.

### Aykırı okuma ve tolerans uyarısı

`|x − x̄| > 4s` olan okuma tabloda **AYKIRI** olarak işaretlenir ve turuncuya
döner. Eşik 4s: 3s gündelik gürültüde bile binde üç yanlış alarm üretir, uzun
bir oturumda bu her yüz okumada bir uyarı demektir. Karşılaştırma okuma
istatistiğe **girmeden önce** yapılıyor; kendi değerini de içeren bir
ortalamaya göre kıyaslamak sapmayı olduğundan küçük gösterir.

**Kendiliğinden dışlamaz.** Okuma anında modal pencere de açmaz — ölçüm
sürerken her aykırı değer için pencere açmak akışı kesip cihazı bekletirdi.
Bunun yerine uyarı şeridinde sayı birikir ve "Aykırı okumaları dışla…"
düğmesi çıkar; oturumu bitirirken işaretli ama dışlanmamış okuma kalmışsa soru
bir kez sorulur.

Ölçüm tolerans bandının dışına çıktığında aynı şerit kırmızı bir sayaçla uyarır;
"Sesli uyar" işaretliyse ayrıca sesli. Şu ana kadar bu yalnızca sonuç satırında
görülüyordu ve operatör grafiğe bakmıyorsa geç fark ediliyordu.

## Onay kuyruğu

Lab sorumlusu için ayrı sayfa (`Ctrl+O`). Onay bekleyen bir sertifikayı bulmak
için geçmiş kayıtlara girip süzgeç kurmak, sonra belgeyi ayrıca açmak
gerekiyordu.

Kuyruk **eskiden yeniye** sıralı — yoğun bir haftada en eski belge listenin
dibinde kalıp orada unutulmasın. Sağ tarafta seçili sertifikanın ölçüm özeti ve
grafiği duruyor:

* **ölçüm oturumu sertifikası** → okumalar sırayla, dışlananlar çarpı ile,
  kesikli çizgi nominal, noktalı çizgiler tolerans. Bir okumanın neden
  dışlandığı ancak dizinin şekline bakınca anlaşılıyor.
* **dalga serisi sertifikası** → şok şok aktarılan enerji, ayarlanan enerji ve
  IEC toleransı çizili. Rapor üretildikten sonra ayarlanan enerji değişmişse
  belgedeki karar ile şimdi hesaplanan karar ayrışır ve bu ayrıca uyarılır —
  onaylayan bunu görmeden imzalamamalı.

**Geri çevir** yeni bir durum eklemiyor, sertifikayı gerekçesiyle birlikte
yumuşak siliyor: ölçüm ve denetim izi yerinde kalıyor, numara serisinde boşluk
oluşmuyor, düzeltilmiş belge yeniden üretilebiliyor. Şemaya "reddedildi" diye
üçüncü bir durum eklemek, sertifikanın var olup da geçersiz sayıldığı bir ara
hâl yaratırdı; oysa onaylanmamış bir sertifika zaten resmî belge değil.

Sertifikayı cihazına bağlayan eşleme (`certificate.SOURCE_JOIN`) kuyrukla
sertifika listesinde **ortak**: iki ekranda iki farklı "hangi sertifikalar var"
cevabı çıkmasın.

## Osiloskop: Keysight DSOX1202A

Osiloskobun bu uygulamada **iki ayrı işi** var ve ikisi aynı veri şeklinde değil.

### 1. Skaler ölçüm — mevcut akışın içinde

`:MEASure:VPP?`, `:MEASure:FREQuency?` gibi sorgular okuma başına tek sayı
döndürür. Bu, `readings` tablosuna, Welford istatistiğine, tolerans kontrolüne
ve sertifikaya olduğu gibi oturuyor; oturum akışında hiçbir şey değişmiyor.
Osiloskop zaten bu büyüklükler üzerinden kalibre edilir.

12 fonksiyon: Vpp, Vamp, Vmaks, Vmin, Vort (DC), Vrms, frekans, periyot,
yükselme/düşme süresi, pozitif darbe genişliği, görev çevrimi.

Yeni oturum ekranında osiloskop seçilince **Kanal** açılırı görünür, NPLC
gizlenir (multimetreye özgü). Ölçülen kanal oturuma yazılır ve sertifikada
"Ölçülen kanal: Kanal 2" satırı olarak basılır — kanal yazmayan bir
"Vpp = 1,984 V" satırı tek başına izlenebilir değil.

Sürücü iki sessiz hata kaynağını açıkça ele alıyor:

* **`+9.9E+37` = "ölçüm yapılamadı".** Sinyal yoksa ya da büyüklük ekranda
  görünmüyorsa cihaz hata vermez, bu sayıyı döndürür. Ham haliyle kaydedilirse
  ortalama 1e37'ye fırlar ve oturum çöp olur. Sürücü bunu yakalayıp ne
  yapılması gerektiğini söyleyen bir hata veriyor.
* **Durdurulmuş cihazda ölçüm donar.** `:STOP` durumunda `:MEASure:VPP?` her
  seferinde aynı değeri döndürür; uygulama bunu N tekrarlı okuma sanar ve
  belirsizliği sıfır hesaplar. `configure` cihazı `:RUN` durumuna alıyor.

### 2. Dalga yakalama — ayrı sayfa, ayrı depolama

Tetikleme başına binlerce (t, V) noktası gelir. Bunlar *aynı büyüklüğün
tekrarlı ölçümü değil*, tek bir olayın örnekleri — `readings` tablosuna
yazmak ortalama ± U hesabını anlamsız kılar ve veritabanını her tetiklemede
on binlerce satır büyütürdü.

Bu yüzden yakalama **CSV dosyası** olarak durur; veritabanında yalnızca künyesi
bulunur: hangi osiloskop, kim, ne zaman, kaç nokta, hangi kanallar, örnekleme
aralığı ve dosyanın **SHA-256** özeti. Özet sayesinde CSV sonradan
değiştirilirse listede "DEĞİŞMİŞ" olarak görünür — ham verinin
değiştirilemezliği kuralı burada da geçerli.

Sayfa yalnızca envanterde dalga yakalayabilen etkin bir cihaz varsa eklenir.

**Akış:** silahlandır (`:SINGle`) → tetikleme bekle → açık kanalları oku →
ortak zaman eksenli tek CSV yaz → tekrar silahlandır.

| Ayar | Ne işe yarar |
|---|---|
| Kanallar | Elle seçilir ya da "ekranda açık olanları kullan" |
| Nokta / kanal | Az nokta = hızlı aktarım. Boş bırakılırsa cihaz varsayılanı |
| Yakalama sayısı | 0 = sınırsız, kullanıcı durdurana kadar |
| Tetikleme zaman aşımı | Süre dolarsa uyarır ve beklemeyi yeniler; durdurmaz |
| Kalibre edilen cihaz | Yakalamayı bir DUT'a bağlar (isteğe bağlı) |
| Klasör | Varsayılan `data/dalgalar/<dut_id>/` |

Tetikleme beklemesi **süresizdir**, bu yüzden ayrı bir `QThread`'de yürür:
ana iş parçacığında olsaydı sinyal gelmediğinde pencere yanıt vermezdi.
"Durdur" anında etkilidir — bekleme döngüsü her turda bayrağa bakıyor,
`terminate()` çağrılmıyor; yarıda kesilen bir VISA okuması cihazı tanımsız
durumda bırakır ve sonraki bağlantı "device busy" ile başarısız olur.

Dosya adı `yakalama_0007_20260810_095503_778.csv` biçiminde. Sıra numarası
klasördeki dosyalara bakılarak üretiliyor; bellekte sayaç tutmak uygulama
kapanıp açılınca aynı klasörde ikinci bir `0001` üretirdi.

CSV biçimi — ilk sütun ortak zaman ekseni, tetikleme anı `t = 0`:

```
time_s,CH1_V,CH2_V
-0.005,0.20312,0.19531
-0.004995,0.24218,0.21093
```

Kanallar farklı uzunlukta gelirse (biri kapatılıp açıldıysa, bellek derinliği
değiştiyse) ortak uzunluğa kırpılır. Kırpmadan yan yana yazmak CSV'yi sessizce
kaydırır ve son satırlar yanlış zamana denk gelir.

---

## Defibrilatör testi

> **Defibrilatör çıkışı osiloskoba doğrudan bağlanamaz.** DSOX1202A girişi
> 300 Vrms (CAT I); defibrilatör 5 kV'a kadar çıkar. Zincir şöyle olmalı:
> defibrilatör → **50 Ω endüktif olmayan yük** → **yüksek gerilim bölücü** →
> osiloskop. Uygulama bölücü oranını ve yük direncini soruyor ve ikisini de
> kayda geçiriyor — bölücü oranı kaydedilmezse CSV sessizce 1000 kat yanlış olur.

Dalga yakalama sayfasında **Test modu** seçilir. Modlar cihaz ayarlarını,
yakalama davranışını, ölçüm zincirini ve uygulanacak çözümlemeyi birlikte
taşır (`callog/testmodes.py`).

| Mod | Varsayılanlar | Çözümleme |
|---|---|---|
| Serbest yakalama | cihazdaki mevcut ayarlar | — |
| Defibrilatör — bifazik şok | 50 V/böl · 5 ms/böl · tetik 50 V · bölücü 1:1000 · tek atım | şok analizi |
| Defibrilatör — monofazik şok | aynı | şok analizi |
| Harici kalp pili darbesi | 5 V/böl · 20 ms/böl · tetik 5 V · bölücü 1:1000 | darbe analizi |

Varsayılanlar **başlangıç noktasıdır**, kural değil: ekranda değiştirilebilir
ve fiilen kullanılan değerler kayda geçer.

Tetikleme eşiği **bölücü öncesindeki gerçek gerilime göredir**. 1:1000
bölücüde 5 V'luk bir eşik osiloskop girişinde 5 mV demekti — cihazın
tetikleme çözünürlüğünün altında kalıyor, tetikleme hiç gelmiyor ve ekran
boş kalıyordu. Varsayılan bu yüzden 50 V. Eşik ekran aralığının dışına
çıkarsa (±V/bölme × 4) alan altında kırmızı uyarı belirir ve yakalama
başlatılırken onay istenir.

### Prob oranı = bölücü oranı

Cihaza harici bölücüyü bildirmenin yolu **prob zayıflatmasıdır**
(`:CHANnel1:PROBe 1000`). Uygulama bölücü oranını cihaza bu şekilde
bildiriyor. Bildirilmezse iki şey birden bozulur:

* Dikey duyarlılık sınırı 1:1 probda **500 µV – 5 V/bölme**'dir. 50 V/bölme
  istendiğinde cihaz `-222,"Data out of range"` döndürür. 1:1000
  bildirildiğinde sınır 0,5 V – 5 kV/bölme olur ve istek geçerlileşir.
* Cihazın ekranı, ölçümleri ve **ekran görüntüsü** bölünmüş gerilimi
  gösterir; rapordaki değerlerle uyuşmaz.

Prob oranı bildirildiği için cihaz **zaten gerçek gerilimi döndürür**;
uygulama üstüne bir kez daha çarpmaz. Yazılım çarpanı `bölücü / prob`
olarak hesaplanıyor (`testmodes.software_factor`) — iki yolun da aynı
sonucu vermesi böyle sağlanıyor.

Bir ayar reddedilirse hata **hangi ayarın** reddedildiğini ve o an geçerli
prob oranına göre izin verilen aralığı yazar; toplu gönderip sonunda tek
kontrol yapmak yalnızca `-222` diyordu.

### Akış

1. Test modu seçilir → ölçek, tetikleme ve zincir alanları modun
   varsayılanlarıyla dolar. Bölücü varsayılanı **1:1000**.
2. Bölücü oranı ve yük direnci gözden geçirilir.
3. **Otomatik ölçekle** (isteğe bağlı) — cihazın kendi Auto Scale'i
   çalıştırılır, bulunan ölçek alanlara yazılır. Sinyali bulmak için; ölçek
   doğruluk bütçesinin parçası olduğu için kayda giren değer sonra elle
   gözden geçirilir.
4. **Ölçekleri cihaza uygula** — prob oranı (önce), V/bölme, s/bölme,
   tetikleme eşiği ve kenar osiloskoba yazılır, ardından cihaz `:RUN` ile
   taramaya alınır. Süpürme burada **AUTO**: ayar yapılırken tetikleme
   gelmese de sinyal ekranda kalsın. NORMal yazıldığında ekran donuyor ve
   operatör ön paneldeki Auto Scale'e basmadan sinyali geri getiremiyordu.
5. **Yakalamayı başlat** → yüksek gerilim uyarısı onaylanır → süpürme
   **NORMal**'e alınır (AUTO'da cihaz sinyal yokken de tarar ve boş bir
   ekran "yakalanmış şok" sanılırdı) → cihaz `:SINGle` ile silahlandırılır
   ve şok beklenir. Zaman aşımı varsayılan olarak kapalı: şoku operatör
   verecek.
6. Şok gelince kanal okunur, ölçek düzeltmesi uygulanır, CSV + cihaz
   ekranının PNG kopyası aynı adla yan yana kaydedilir, çözümleme yapılır.

### Seri ölçüm (10×)

**Ölçüm sayısı (seri)** alanına 10 yazılır — ya da yanındaki **10×**
düğmesine basılır. Cihaz her şoktan sonra kendini yeniden silahlandırır;
10 ayrı CSV, 10 ayrı ekran görüntüsü ve 10 ayrı çözümleme çıkar. Rozet
ilerlemeyi `● 3/10` biçiminde gösterir.

Serideki bütün yakalamalar tek bir **seri anahtarı** altında toplanır
(`SER-YYYYMMDD-HHMMSS`); listede "Seri" sütununda `3/10` biçiminde görünür.
Seri bittiğinde enerji ve tepe gerilimin ortalaması ± standart sapması
durum çubuğuna yazılır.

### Seri raporu (PDF)

Seriye ait herhangi bir satır seçilip **Seri raporu (PDF)** ile üretilir.
Bindirmeli grafik kendi sayfasından başlar — tam sayfa okunması gereken bir
bölüm, önceki bölümün artığıyla sayfayı paylaşması okumayı zorlaştırıyordu.
Uygunluk değerlendirmesi ise tablosu ve **Sonuç** satırıyla birlikte tek
parça tutulur (`KeepTogether`): belgenin en önemli cümlesinin gerekçesinden
kopup tek başına bir sayfaya düşmesi kabul edilemez.

Belge şunları taşır:

* **Künye** — rapor no, seri anahtarı, test modu, **test edilen cihaz**
  (şirket, üretici, model, seri no, cihaz tipi), ölçüm zinciri ve
  **ölçümü yapan osiloskobun seri no / kalibrasyon sertifikası**.
* **Bindirmeli grafik** — serideki bütün dalgalar soluk gri, **ortalama
  dalga** koyu turuncu ve kalın olarak en üstte. Şokların birbirinden
  ayrıldığı bölge doğrudan görünür; ayrı ayrı çizilen n grafikte bu
  görünmüyor. Ortalama, kayıtların **kesişen** zaman aralığında ortak bir
  eksene doğrusal aradeğerlemeyle taşınarak hesaplanır — kaymış örnekleri
  doğrudan toplamak dalgayı yayvanlaştırır ve tepeyi olduğundan küçük
  gösterirdi.
* **Seri istatistiği** — her büyüklük için (enerji, tepe gerilim, tepe akım,
  faz süreleri, tilt, τ): n, ortalama, örnek standart sapması s, A tipi
  standart belirsizlik u = s/√n, genişletilmiş belirsizlik U = 2u (k=2,
  ≈%95), en küçük ve en büyük. Sertifikalardaki `Statistics` sınıfı
  kullanılıyor: aynı kuralın iki yerde iki türlü hesaplanması, iki belgede
  farklı sayılar demek olurdu.
* **Uygunluk değerlendirmesi** — ayarlanan enerji, ölçülen ortalama, sapma,
  U ve izin verilen tolerans; ardından **Sonuç: UYGUN / UYGUN DEĞİL /
  BİLGİLENDİRME AMAÇLI**.
* **Ölçüm ölçüm tablo** — her şok kendi satırında; enerji, tepe, süre, dosya.
* **Ekran görüntüleri** — her şokun cihazdan alınmış PNG'si, iki sütunlu ızgarada.
* **Kaynak dosyalar** — her kaydın SHA-256'sı ve bütünlük denetimi sonucu.

Seri raporları ayrı numara dizisinden gelir (`SERI-SOK-CAL-MED-YYYY-NNNN`);
tek şok raporlarının numaralarını kaydırmaz. Numara serinin bütün
kayıtlarına yazılır, listede hangi satıra bakılırsa bakılsın görünür.

> **A tipi bileşen yalnızca tekrarlanabilirliktir.** Bölücü oranının, yük
> direncinin ve osiloskobun dikey doğruluğunun katkıları bu belirsizliğe
> dahil değildir; rapor bunu açıkça yazıyor.

### Dalga sertifikasyonu

Seri raporu üretildiği anda **sertifika defterine** de işlenir; skaler ölçüm
oturumlarının sertifikalarıyla aynı defter, aynı ekran, aynı işlemler:

* **Cihaz sayfası → Dalga ölçümleri** sekmesinde cihazın bütün seri
  ölçümleri listelenir: tarih, test modu, şok sayısı, ayarlanan enerji,
  sertifika no, sonuç ve durum (onay bekliyor / onaylandı / silinmiş).
  Cihaz özetindeki sayaçlara da girer.
* **Geçmiş → Sertifikalar** sekmesinde ölçüm oturumu sertifikalarıyla yan
  yana görünür; **Tür** sütunu ikisini ayırır. Onaylama, yumuşak silme ve
  geri alma aynı düğmelerden yapılır — `certificates` tablosu tek olduğu
  için bu işlemler zaten kaynaktan bağımsız çalışıyordu.

`certificates.session_id` ile `certificates.series_id` alanlarından **tam
olarak biri** dolu olmak zorunda (CHECK kısıtı): ikisi de boşsa sertifikanın
neyi belgelediği belirsiz kalır, ikisi de doluysa iki farklı ölçüme tek
numara verilmiş olur. Sertifika numarası olarak rapor numarası kullanılır —
belgeye ikinci bir numara basmak, aynı çıktının iki adı olması demekti.

Aynı seri yeniden raporlanırsa **yeni satır açılmaz**, mevcut sertifika
güncellenir ve **onayı düşer**: içerik değiştiği için eski onay artık o
belgeye ait değildir.

#### Uygunluk kararı

Karar, cihazda **ayarlanan enerji** (Dalga sayfası → *Ayarlanan enerji*)
kaydedilmişse verilir:

| | |
|---|---|
| Tolerans | ± ayarın %15'i **ya da** 3 J — hangisi büyükse (IEC 60601-2-4) |
| Karar kuralı | \|ortalama − ayarlanan\| + U ≤ tolerans |

Karar kuralı çoklu-okuma sertifikasınınkiyle birebir aynı (`stats.verdict_ok`,
`mean` kipi). Uygunluğun iki farklı tanımı olsaydı, hangi belgeye bakıldığına
göre değişen bir sonuç çıkardı.

Alan boş bırakılırsa sonuç **BİLGİLENDİRME AMAÇLI** olur ve rapor bunun
nedenini yazar. Ölçülen 5.1 J'nin uygun olup olmadığı, ancak "5 J'ye
ayarlandı" bilgisiyle anlam kazanır; sessizce "uygun" demek, hiç
değerlendirilmemiş bir cihazı geçmiş göstermek olurdu.

### Toplu değerlendirme raporu

Seri raporu tek bir enerji ayarındaki n şoku değerlendirir. Ama bir
defibrilatörün kalibrasyonu tek noktada bitmez: 2 J'den 360 J'ye kadar
bütün kademelerde doğru olması gerekir. **Cihazlar → Dalga ölçümleri →
Toplu değerlendirme (PDF)** o kademeleri tek belgede toplayıp cihaz
hakkında tek bir karar veriyor (`summaryreport.py`).

Belge bilerek sade: ekran görüntüsü, bindirmeli dalga grafiği ve şok şok
tablolar burada yok — onlar zaten her seri raporunda duruyor ve kaynak
belge olarak numarasıyla listeleniyor. Buradaki soru tek tek şoklar değil,
**cihazın çalışma aralığı boyunca davranışı**. İçerik: kademe kademe
sonuç tablosu (ayarlanan, n, ortalama, s, U, sapma, tolerans, karar),
aralık boyunca bağıl sapma grafiği, genel değerlendirme ve kaynak seri
raporlarının listesi.

Sapma grafiğinin ekseni **logaritmik**: kademeler kabaca geometrik
ilerliyor ve doğrusal eksende 2–30 J aralığı sola yığılıp okunmaz hâle
geliyordu. Y ekseni **sapmalara** göre ölçekleniyor, tolerans bandına
göre değil: düşük enerjilerde 3 J'lik taban toleransı %200'e çıkarıyor ve
bandı sığdırmaya çalışmak bütün noktaları sıfır çizgisine yapıştırıyordu.

**Bir kademe bile uygun değilse belge uygun değildir** — belge cihazın o
kademelerde kullanılabilir olduğunu söyler, kademelerin ortalamasını değil.

Toplu rapor `summary_reports` tablosunda ayrı bir defterde ve
`TOPLU-SOK-CAL-MED-YYYY-NNNN` biçiminde ayrı bir numara dizisinde tutulur.
Neden `certificates` tablosunda değil: oradaki CHECK kısıtı bir belgenin
**tam olarak** bir ölçüm oturumuna ya da bir seriye ait olmasını şart
koşuyor ve bu bilinçli bir kural. Toplu rapor tanımı gereği N seriyi
kapsıyor; kısıtı gevşetmek "bu belge neyi belgeliyor" sorusunu bütün
sertifikalar için belirsizleştirirdi.

#### Faz tespiti ve kaba kuantalama

Osiloskobun 8 bitlik dikey çözünürlüğü, dikey ölçek büyüdükçe kabalaşır.
Yüksek enerjilerde kayıt yalnızca birkaç on kuantalama adımına sığabiliyor
ve o zaman **bir ADC adımı**, faz eşiğinin (tepe değerin %5'i) üstüne
çıkıyor: 30 J ölçümlerinde adım 40 V, eşik 28 V idi. Taban gürültüsünün
tek örneklik sıçraması "eşiği aşan ilk bölge" olarak bulunuyor, gerçek
ikinci faz hiç görülmüyor ve şok **monofazik** sanılıyordu — enerji yalnızca
birinci fazdan hesaplandığı için 30 J yerine 24 J çıkıyordu.

Bu yüzden faz olamayacak kadar kısa bölgeler atlanıyor
(`defib.MIN_PHASE_DURATION_S`, 50 µs): gürültü sıçramasının ~10 katı,
en dar kalp pili darbesinin ~10'da biri.

Çözümleme **yakalama anında** hesaplanıp `analysis_json` olarak saklanıyor —
rapor, operatörün o an gördüğü sonucu yeniden üretebilsin diye. Çözümleme
kodu düzeltildiğinde saklanan sonuç eskiyor; `waveform.reanalyze()` ham
CSV'den yeniden hesaplayıp kayda yazıyor ve işlemi denetim kaydına
geçiriyor. Ham CSV'ye ve SHA-256 özetine dokunulmuyor: değişen yalnızca
türetilmiş veri.

### Ekran görüntüsü zamanlaması

Ekran görüntüsü **yakalama iş parçacığında**, tetiklemeden hemen sonra ve
cihaz yeniden silahlandırılmadan önce alınır. Sıra: tetikleme → bekle →
ekran görüntüsü → dalgayı oku → yayımla → yeniden silahlandır.

Eskiden arayüz iş parçacığında, `captured` sinyali işlenirken alınıyordu; bu
arada yakalama döngüsü bir sonraki tura geçip `:SINGle` ile ekranı siliyordu
ve görüntü **boş** çıkıyordu.

Buna ek olarak **Ekran görüntüsü gecikmesi** alanı var (varsayılan 0,6 s):
cihaz edinimi bitirdiğini bildirdiğinde ekranı henüz çizmemiş olabiliyor.
Görüntü hâlâ boş geliyorsa bu değer artırılır.

### CSV al — tetikleme beklemeden

**Ekran görüntüsü al** düğmesinin yanındaki **CSV al**, cihazda o an ekranda
duran dalgayı tetikleme beklemeden okur ve CSV + PNG olarak kaydeder. Sinyal
zaten ekrandayken tekrar şok vermek zorunda kalmamak için. Okumadan önce
cihaz durdurulur: cihaz tararken kanallar arka arkaya okunursa iki kanal
farklı edinimlerden gelir ve ortak zaman ekseni yalan söyler. Kayıt
`Tetiklemesiz elle alım (CSV al)` notuyla işaretlenir.

### Hesaplanan büyüklükler

Tepe gerilim ve akım, faz süreleri, **eğim (tilt)**, kesilmiş üstel bozunumun
**zaman sabiti τ**, ve yüke aktarılan **enerji** (E = ∫v²/R dt, yamuk kuralı).

Faz sınırları tepe değerin %5'ini geçen kesintisiz bölge olarak belirlenir.
Daha yüksek bir eşik faz süresini sistematik olarak kısa ölçer, daha düşüğü
gürültüyü darbe sanar. Taban hattı tetikleme öncesi bölgenin **ortancasıdır** —
ortalama değil, çünkü tek bir ön darbe ortalamayı kaydırır ve tüm faz
sınırları kayar.

τ en küçük karelerle bulunur (ln|v| doğrusal, eğimin tersi τ); iki uç nokta
kullanılsaydı tek bir gürültülü örnek sonucu savururdu.

**Bu değerler yakalanan dalgadan hesaplanır, sertifikalı bir defibrilatör
analizörü ölçümü değildir.** Yük direncinin gerçek değeri ve osiloskobun
dikey doğruluğu doğrudan sonuca girer.

### Kırpma denetimi

Osiloskop kırpılan sinyali hata olarak bildirmez: ekranın dışına taşan tepe
düz bir çizgi olarak kaydedilir, tepe gerilim olduğundan küçük ölçülür ve
enerji düşük çıkar. Tepe, ekran aralığının %98'ini geçtiğinde uygulama uyarır.

### Şok raporu (PDF)

Yakalama listesinden bir kayıt seçilip **Şok raporu (PDF)** ile üretilir.
Rapor **iki görüntüyü birlikte** taşır, çünkü ikisi farklı soruya cevap verir:

* **Kayıt dosyasından çizilen grafik** — ölçülen veri. Faz bölgeleri renkli,
  tetikleme anı ve tepe değerler işaretli. Raporun tablosuyla aynı kaynaktan
  geldiği için sayılarla birebir tutarlı.
* **Osiloskop ekran görüntüsü** — cihazın o an gördüğü. Bölme ayarlarını,
  tetikleme işaretini ve cihaz üzerindeki okumaları içerir.

Grafik çizilirken 20 000 nokta **min/maks zarfıyla** seyreltilir. Basit
"her N'inci noktayı al" seyreltmesi kesilmiş üstel dalgada tepe noktasını
kaçırıyor — tepe tek bir örnekte olabiliyor ve grafik gerçekte olduğundan
alçak görünüyor. Bucket başına en küçük ve en büyük değeri birlikte çizmek
osiloskopların yaptığı şey ve dik kenarları koruyor.

Raporda ayrıca: test edilen cihaz, ölçüm zinciri (bölücü, yük, ölçekler),
osiloskobun kendi kalibrasyon sertifikası, çözümleme tablosu, kaynak
dosyaların adları ve **SHA-256 özetleri** ile bütünlük denetimi sonucu.

Rapor numarası ayrı seriden gelir: `SOK-CAL-MED-YYYY-NNNN`. Simülasyon
raporları `SIM-SOK-…` önekiyle numaralanır ve çapraz filigran taşır — resmî
seriyi tüketmezler.

Kayıt dosyası değiştirilmişse rapor üretimi durmaz ama önce uyarır ve
bütünlük denetimi sonucu belgeye olduğu gibi yazılır.

### Ekran görüntüsü

**Ekran görüntüsü al** düğmesi cihazdan `:DISPlay:DATA? PNG,COLor` ile
ekranın PNG kopyasını çeker — yakalama sürmese de çalışır. Her yakalamada da
kendiliğinden alınır ve CSV ile **aynı adı** taşır
(`yakalama_0004_20260810_104651_095.csv` / `.png`), böylece klasörde yan yana
duran iki dosyanın aynı olaya ait olduğu dosya adından anlaşılır.

Neden cihazdan alınıyor da uygulamada çizilmiyor: rapora giren görüntünün
*cihazın gördüğü* olması gerekiyor. Uygulamanın kendi çizimi bölme ayarlarını,
tetikleme işaretini ve cihaz üzerindeki ölçüm okumalarını içermez; denetimde
"ekranda ne vardı" sorusunun cevabı o dosyadır.

PNG'nin SHA-256 özeti de kaydediliyor. CSV sağlam ama PNG değiştirilmişse
kayıt "DEĞİŞMİŞ" olarak işaretlenir.

---

## Uygunluk kriteri

Tolerans **her zaman ±** olarak uygulanır; girilen işaret yok sayılır. Kararın
neye bakacağı ölçüm ayarlarından seçilir:

| Kriter | Kural | Ne zaman |
|---|---|---|
| Ortalama ± U | \|x̄ − nominal\| + 2u ≤ T | Kalibrasyonda yaygın karar kuralı |
| Tüm okumalar | min ≥ nominal−T ve maks ≤ nominal+T | Kararsız cihazlarda ortalamanın gizlediği sapmaları yakalar |

Seçim oturumla birlikte kaydedilir ve sertifikaya basılır.

## Cihazlar defteri

Laboratuvara bir kez gelen cihaz genelde tekrar gelir. **Cihazlar** sekmesi her
cihazın tüm geçmişini tek yerde toplar. Dört alt sekme:

**Özet ve ölçümler** — cihaz künyesi, ölçüm/dalga serisi/sertifika/belge
sayıları ve o cihaza ait tüm oturumlar (tarih, fonksiyon, nominal, operatör,
sertifika no, sonuç).

**Dalga ölçümleri** — cihazın defibrilatör seri şok testleri: tarih, test modu,
şok sayısı, ayarlanan enerji, sertifika no, sonuç ve onay durumu. Oturumlarla
aynı tabloya sıkıştırılmadı: sütunlar örtüşmüyor (birinde fonksiyon/nominal,
burada şok sayısı/enerji) ve tek tabloda yarısı boş satırlar çıkardı. Ayrıntı
için bkz. [Dalga sertifikasyonu](#dalga-sertifikasyonu).

**Seyir** — aynı ölçüm noktasının yıllar içindeki değişimi. Nokta başına ortalama,
hata çubukları U (k=2), kesikli çizgi nominal. Toplam değişim altta yazılı.
Cihazın sürüklenmesini gösteren bu grafik, elle tutulan Excel'lerde görülemeyen
şeydir.

X ekseni **ölçüm sırası değil gün**: iki kalibrasyon arasında altı ay da
olabilir altı gün de, sıra numarası bu farkı gizler ve "yılda ne kadar
kayıyor" sorusunun cevabını anlamsız kılar.

"Eğilim ve tolerans bandı" işaretliyken üç şey eklenir (`trend.py`, Qt'siz):

* **tolerans bandı** — nominal ± tolerans arası soluk dolgu. Tolerans zaman
  içinde değişmişse en son ölçümünki kullanılır: bugünkü kabul ölçütü o.
* **eğilim çizgisi** — takvim gününe göre en küçük kareler uyumu. Uyum zayıfsa
  (kısa gözlem aralığı) çizgi kesikli yerine **noktalı** çizilir.
* **sınır aşım tahmini** — "bu hızla giderse 10.4 V sınırını 2028-03-14
  tarihinde aşar". Yalnızca *dışarı doğru* giden bir eğim için hesaplanır;
  bant içinde kalan ya da içeri gelen bir cihaz için böyle bir soru yok.

En az üç ölçüm gerekiyor: iki nokta her zaman kusursuz bir doğru verir ve
ondan çıkarılan yıllık hız ölçüden çok gürültüyü anlatır. Gözlem aralığı 30
günden kısaysa tahmin üretiliyor ama **güvenilmez** olduğu açıklamada yazıyor.

**Belgeler** — uygulamadan önceki döneme ait PDF raporlar ve diğer belgeler cihaz
kaydına iliştirilir. Dosya uygulamanın kendi klasörüne (`data/belgeler/<id>/`)
**kopyalanır** ve SHA-256 özeti alınır; kaynak dosya taşınsa, silinse veya ağ
sürücüsü kopsa bile kayıt kırılmaz. Liste her açılışta dosyanın yerinde ve
değişmemiş olduğunu doğrular. Bağlantı kaldırılsa da kopya diskte kalır.

**Yeni cihaz ekle** — cihazı hiç ölçmeden envantere kaydeder (örn. yalnızca eski
bir belge iliştirmek için). Şirket, üretici, model, seri no zorunlu; cihaz tipi
ve not isteğe bağlı. Aynı üretici + model + seri no ile daha önce kayıt
açılmışsa yeni satır oluşturulmaz — mevcut cihaz seçilir. Bu, oturum başlatmadan
bağımsız bir yol: eskiden tek yol Yeni oturum ekranındaki formdu.

"Bu cihaz için yeni ölçüm" düğmesi formu doldurup Yeni oturum sekmesine geçer.

Yeni oturum ekranındaki "Geçmiş cihazlar" sekmesi de aynı listeyi sunar; seçince
önceki ölçümün fonksiyon, nominal, tolerans ve kriter değerleri getirilir.

Aynı seri no + üretici + model için ikinci bir kayıt açılmaz; oturumlar tek bir
cihaz kaydına bağlanır — bu kural hem oturum başlatırken hem "Yeni cihaz ekle"de
aynı şekilde uygulanır.

## Sertifikadaki ölçüm grafiği

PDF ve DOCX sertifikaya ölçümün grafiği gömülür (`chart.py`, reportlab.graphics
ile vektör — Qt gerektirmez, ekransız çalışır).

**Üst panel** — okumaların zamana göre seyri:

| Öğe | Anlamı |
|---|---|
| Noktalar + çizgi | Kaydedilen okumalar |
| Dikey çubuklar | ±s — **tek bir okumanın** standart sapması |
| Yeşil çizgi | Ortalama x̄ |
| Yeşil bant | x̄ ± U (k=2) — **sonucun** belirsizliği |
| Kesikli çizgi | Nominal değer |
| Gri bant | Tolerans bandı |
| Kırmızı × | Dışlanan okumalar (hesaba katılmaz) |

Hata çubuğu ile belirsizlik bandı bilinçli olarak ayrı: çubuklar tek okumanın
saçılımını, bant sonucun belirsizliğini gösterir. İkisi karıştırılmasın diye
açıklama grafiğin altına basılır.

**Alt panel** — okumaların dağılımı (histogram). Ölçümün simetrik ve tek tepeli
olup olmadığı buradan görülür; kayma veya iki tepe kararsız bir cihaza ya da
ısınmanın bitmemiş olmasına işaret eder.

Okuması olmayan oturumda grafik atlanır, belge yine tam üretilir.

## Geçmiş kayıtlar

İki sekme: **Ölçüm oturumları** ve **Sertifikalar**.

Oturum filtreleri: serbest arama, kalibre edilen cihaz, referans cihaz, durum,
yalnızca kendi ölçümlerim, **tarih aralığı**.

Sertifika filtreleri: serbest arama, cihaz, durum (onay bekleyen / onaylanmış /
silinmiş), sonuç (uygun / uygun değil / bilgilendirme), **tarih aralığı**.

**Tarih aralığı süzgeci** hazır seçenekler (son 7 / 30 / 90 gün, bu yıl) ve
özel aralık sunar — "geçen ay yapılanlar" en sık sorulan soru. Karşılaştırma
ISO metin üzerinden yapılıyor: damgalar `YYYY-AA-GGThh:mm:ss+00:00` biçiminde
saklandığı için sözlük sırası zaman sırasıyla aynı ve ayrıca bir tarih
ayrıştırması gerekmiyor. Bitiş tarihi bir gün ileri alınıp `<` ile
karşılaştırılıyor; `<= '2026-08-11'` o günün saat bilgisi taşıyan hiçbir
ölçümünü almazdı. Sınır: damgalar UTC, seçilen gün yerel — gece yarısına yakın
alınmış bir ölçüm komşu güne düşebilir. Gün bazlı süzme için kabul edilebilir;
saniye hassasiyeti gerektiğinde denetim kaydına bakılıyor.

Çıktılar: **PDF** (resmî sertifika, kayıt oluşturur), **DOCX** (düzenlenebilir
Word — kurum anteti ve ek notlar için), **XLSX** (özet + noktalar + ham veri).

Excel'deki **Noktalar** sayfası tek noktalı oturumda da yazılıyor: dosyayı
alan kişi sayfanın varlığına göre iş yapıyorsa, sayfanın bazen olup bazen
olmaması en can sıkıcı sürpriz olurdu. Ham veri sayfasında her okumanın hangi
noktaya ait olduğu ayrı sütunda.

### Toplu işlem ve karşılaştırma

Liste **çoklu seçim** kabul ediyor (Ctrl / Shift). Dışa aktar menüsünden:

* **Seçilenleri Excel'e aktar** — seçilen klasöre oturum başına bir `.xlsx`.
  Tek dosyada birleştirilmiyor: on oturumu tek dosyaya koymak otuz sayfalık,
  gezilemeyen bir kitap üretirdi.
* **Seçilenlere sertifika üret** — uygun olmayanlar (sürüyor, silinmiş,
  okuması yok, zaten sertifikalı) **atlanıyor ve neden atlandığı yazılıyor**.
  Toplu işlemde sessizce atlanan bir kayıt, üretildiğini sanılan bir sertifika
  demek.

**Karşılaştır** seçili oturumların okumalarını aynı grafikte üst üste çiziyor.
Karşılaştırma **ölçüm noktası** düzeyinde: çok noktalı bir oturumda 10 V ile
1 kΩ'u aynı Y ekseninde çizmek ikisini de okunmaz yapardı. Birimi ilk seriden
farklı olan noktalar grafiğe alınmıyor ve altta neden alınmadığı yazıyor. X
ekseni okuma sırası, geçen süre değil: iki oturum farklı okuma periyodu
kullanmış olabiliyor ve saniye ekseninde eğriler yapay olarak kayıyor.

Dışa aktarma ve toplu işlemler tek bir menü düğmesinde toplandı; altı yan yana
düğme satırı sayfanın en dar çizilebileceği genişliği belirliyordu (1501 px →
1251 px).

### Sertifika önizlemesi

**Önizle** belgeyi uygulama içinde gösteriyor (Qt'nin `QtPdf` modülü) — yanlış
üretilmiş bir sertifikayı fark etmek için dosyayı harici görüntüleyiciye
gönderip kapatmak gerekmesin. Onay kuyruğunda da var: onaylayan belgenin
kendisini görmeden imzalamamalı. Modül bazı Qt kurulumlarında paketlenmemiş
oluyor; o durumda dosya sessizce işletim sistemine devrediliyor.

### Genel arama (Ctrl+K)

Tek kutu: seri no, sertifika no, firma, model ya da oturum adı. Sonuçlar
türlerine göre gruplanıyor (sertifika · dalga serisi · ölçüm oturumu · cihaz ·
referans cihaz) ve Enter ilgili sayfayı açıp kaydı seçiyor. Sertifika en üstte:
elinde numara olan biri belgeyi arıyordur, cihaz kartını değil.

En az iki karakter isteniyor ve tür başına en fazla 8 sonuç dönüyor —
"SN-2024" yazınca 200 oturum dönüp aradığı cihazı listeden düşürmesin. Arama
her tuşta değil, yazma durunca çalışıyor.

### Oturum adı

Her oturum bir adla kaydedilir. Varsayılan ad **firma · seri no · tarih saat**
biçiminde üretilir (örn. `Örnek Devlet Hastanesi · SN-2024-0871 · 2026-08-06 18:34`);
Yeni oturum ekranındaki alan boş bırakılırsa bu ad kullanılır, dolu bırakılırsa
kendi adınız geçerli olur. Geçmiş kayıtlarda "Yeniden adlandır" ile (veya satıra
çift tıklayarak) değiştirilir; boş bırakmak varsayılana döndürür. Ad sertifikaya
ve Excel çıktısına da basılır.

### Oturum silme

Sertifika silmeyle aynı mantık: kayıt veritabanından çıkmaz, `deleted_at`,
`deleted_by` ve zorunlu gerekçeyle işaretlenir. Ham okumalar zaten
tetikleyicilerle korunuyor ve silinemiyor — oturumu gerçekten silmek onları
sahipsiz bırakırdı.

İki koruma var: **devam eden** bir oturum silinemez (önce bitirilir) ve
**geçerli sertifikası olan** bir oturum silinemez (önce sertifika silinir).
Silinmiş oturumlar Durum filtresinde "Silinmiş" seçilince yalnızca yöneticiye
görünür; yönetici geri alabilir. Silinen oturum cihaz defterindeki sayımlara ve
seyir grafiğine dahil edilmez.

### Sertifika silme

Silme **yumuşak silmedir**: kayıt veritabanından çıkmaz, `deleted_at`,
`deleted_by` ve gerekçeyle işaretlenir. Böylece numara serisinde boşluk oluşmaz,
ölçüm verisi ve denetim izi korunur. Gerekçe zorunludur.

Silme yetkisi lab sorumlusu ve yöneticide. **Silinmiş kayıtları yalnızca
yöneticiler görür** (listede üstü çizili); yönetici geri de alabilir.

Aynı kurallar dalga seri sertifikaları için de geçerli — `certificates`
tablosu tek olduğu için onay/silme/geri alma işlemleri sertifikanın
kaynağından bağımsız çalışır. Listede **Tür** sütunu ("ölçüm oturumu" /
"dalga serisi") ikisini ayırır.

## Roller ve görünürlük

Kurallar tek yerde: `callog/perms.py`. Arayüz **gizler**, işlem katmanı
**reddeder** — ikisi birden gerekiyor, çünkü gizlenmiş bir düğme kısayolla ya da
doğrudan çağrıyla tetiklenebilir. Yetkisi olmayan bir sayfa gri gösterilmez,
hiç eklenmez.

| | Operatör | Lab sorumlusu | Yönetici |
|---|---|---|---|
| Ölçüm yapmak, sertifika üretmek | ✓ | ✓ | ✓ |
| Dalga yakalamak (osiloskop) | ✓ | ✓ | ✓ |
| Cihaz defteri, belge eklemek | ✓ | ✓ | ✓ |
| Oturum yeniden adlandırmak | ✓ | ✓ | ✓ |
| Sertifika onaylamak | — | ✓ | ✓ |
| Oturum / sertifika silmek | — | ✓ | ✓ |
| Belge bağlantısı kaldırmak | — | ✓ | ✓ |
| **Denetim kaydı (log)** | — | ✓ | ✓ |
| Referans cihaz bilgisi görmek | — | ✓ | ✓ |
| Referans cihaz bilgisi düzenlemek | — | — | ✓ |
| Kullanıcı listesi ve yönetimi | — | — | ✓ |
| Silinmiş kayıtları görmek / geri almak | — | — | ✓ |

Operatörde Yönetim sayfası ve menüsü yok, "Silinmiş" durum süzgeci listede
görünmüyor, silme/geri alma/onaylama düğmeleri çizilmiyor. Ana ekrandaki
"Onay bekleyen" sayacı da gizli: operatör o kuyruğa müdahale edemiyor.

Roller yığılımlı tanımlanmadı ("yönetici = lab sorumlusu + fazlası"). Kısa
görünürdü ama "lab sorumlusu neden bunu yapabiliyor?" sorusunun cevabını iki
tanım arasında aramaya zorlardı.

## Yönetim sayfası

Bölümler role göre eklenir: **Kullanıcılar** (yalnızca yönetici — ekle, rol
değiştir, parola sıfırla, devre dışı bırak), **Referans cihazlar** (kalibrasyon
sertifika no, sertifika tarihi ve geçerlilik tarihi; düzenleme yalnızca
yönetici), **Yetki matrisi** (salt okunur), **Denetim kaydı** (hash zinciri
doğrulama, işlem türü, tarih aralığı ve serbest metin süzgeci, CSV'ye aktarma).

**Yetki matrisi** hangi rolün neyi yapabildiğini tablo halinde gösterir — yeni
personele rol atarken ve denetimde "yetkilendirme nasıl?" sorusuna cevap
verirken gerekiyor. Tablo `perms._TABLE`den **üretiliyor**; ekranın kendi
listesi olsaydı bir yetki değiştiğinde ikisi ayrışır ve ekran yanlış bilgi
verirdi.

**Denetim kaydı dışa aktarma** süzgece uyan bütün satırları CSV'ye yazar —
ekranda gösterilen ilk 500 satırla sınırlı değil. `prev_hash` ve `hash`
sütunları da yazılıyor: dosyayı alan denetçi zinciri veritabanı olmadan da
doğrulayabilsin. Özet sütunları olmayan bir döküm "bu satırlar değişmemiş"
iddiasını taşıyamaz. Dosya `utf-8-sig` ile yazılıyor; Excel BOM'suz UTF-8'i
sistem kod sayfası sanıyor ve Türkçe karakterler bozuk görünüyor. Dışa
aktarmanın kendisi de denetim kaydına geçiyor (`audit.export`).

### Veritabanı yedeği

Yönetim menüsünden **Veritabanını yedekle** (`Ctrl+B`) `data/yedek/` altına
zaman damgalı bir kopya yazar ve en yeni 10 kopyayı saklar. Durum çubuğunda
son yedeğin yaşı sürekli görünür; yedek yoksa ya da 7 günden eskiyse hem etiket
uyarı rengine döner hem ana ekranda bildirim çıkar.

`shutil.copy` yerine SQLite'ın kendi yedekleme API'si kullanılıyor: WAL kipinde
açık bir bağlantı varken dosyayı kopyalamak, henüz ana dosyaya aktarılmamış
işlemleri dışarıda bırakır — kopya sessizce eksik olur ve bu ancak geri dönmek
gerektiğinde fark edilir. API okuma tarafında çalıştığı için ölçüm sürerken de
yedek alınabiliyor.

**Sertifika tarihi ile geçerlilik tarihi ayrı alanlar.** Pano ve cihaz
listesi geçerlilik tarihine bakıp geçmişte kalmışsa "SÜRESİ DOLMUŞ" yakıyor;
sertifikanın düzenlenme tarihi oraya yazılsaydı kalibrasyonu geçerli her
cihaz süresi dolmuş görünürdü. Raporlar ikisini de ayrı satırda yazıyor.

**Kullanıcı silme yok.** Silinen bir kullanıcının geçmiş ölçümleri sahipsiz kalır
ve izlenebilirlik zinciri kopar; ayrılan personel devre dışı bırakılır. Son etkin
yöneticinin rolü düşürülemez ve devre dışı bırakılamaz — aksi halde uygulama
yönetilemez hale gelir.

---


---

## Test

Qt, pyvisa veya reportlab kurulu olmadan çalışır — yalnızca standart kütüphane kullanır:

```bash
python tests/smoke_test.py
```

Doğruladığı şeyler: şema kurulumu, parola hash'i, denetim kaydı hash zinciri
(kasıtlı kurcalama dahil), simülasyon sürücüsü, Welford istatistiği,
ham verinin değiştirilemezliği, sertifika hesabı ve SIM- numara serisi.

Ayrıca Qt gerektirmeyen dört yeni modül: **kararlılık** (dört durumun her
biri, eğimin okuma periyoduyla ölçeklenmesi, aykırı okumanın bulunması ve
sıfır sapmada aranmaması), **eğilim** (uyum, r², sınır aşım tarihi, zaten bant
dışında olan cihaz, kısa gözlem aralığının güvenilmez sayılması),
**yedekleme** (kopyanın gerçekten kullanılabilir olması — WAL kipinde düz
dosya kopyalamanın eksik veri bırakacağı bu testin asıl sorduğu şey — ve eski
yedeklerin budanması), **bildirimler** (yetkiye göre budanma, önem sırası,
simülasyon cihazının kalibrasyon uyarısı üretmemesi) ile **yetki matrisinin**
`perms._TABLE` ile birebir örtüşmesi.

Arayüz testi ekransız çalışır ve gerçek akışı baştan sona yürütür:

```bash
python tests/gui_smoke_test.py
```

Gezinme, tema değişimi, cihaz bağlantısı, izleme/kayıt ayrımı, saniye ekseni,
min/maks, grafik takip ve yakınlaştırma davranışı, DUT geçmişi, yönetim
işlemleri, PDF/Excel çıktısı, Türkçe font kapsamı, rol tabanlı gizleme
(her rol için gerçek pencere kurulup sayfa ve düğme görünürlüğü okunuyor) ve
osiloskop entegrasyonu (skaler ölçüm, geçersiz değer reddi, uçtan uca dalga
yakalama, CSV gidiş-dönüşü, kurcalanan dosyanın tespiti).

Ayrıca defibrilatör yolunun tamamı: `-222,"Data out of range"` (1:1 probda
50 V/bölme reddediliyor, 1:1000'de kabul ediliyor), prob oranı bildirilmişken
**çift ölçekleme yapılmaması**, otomatik ölçekleme, ekran dışı tetikleme
eşiğinin uyarılması, tetiklemesiz **CSV al**, seri ölçüm (n ayrı dosya +
dağılım özeti) ve VISA adres eşleştirmesi (`sqlite3.Row` için `.get()`
çağrılmaması dahil — bu hata "Otomatik bul"u sessizce çalışmaz hâle
getiriyordu).

Seri raporu için: ortalama dalganın ortak eksende ve **kesişim** üzerinden
kurulması, istatistiğin (s, u = s/√n, U = 2u, en küçük/en büyük) doğruluğu,
serinin tek anahtar altında toplanması, rapor numarasının ayrı diziden
gelmesi ve serideki **her** ölçümde ekran görüntüsünün dolu olması.

Dalga sertifikasyonu için: `certificates` CHECK kısıtının kaynaksız ve çift
kaynaklı satırları reddetmesi, seri raporunun sertifika defterine işlenmesi,
yeniden üretimin **ikinci satır açmayıp** onayı düşürmesi, uygunluk kararının
IEC toleransıyla (%15 / 3 J tabanı) hesaplanması, ayarlanan enerji yokken
karar verilmemesi, serinin cihaz sayfasında ve sertifika listesinde
görünmesi, onay/silme/geri alma işlemlerinin oturum sertifikalarıyla aynı
yoldan çalışması.

Yeni ekranlar için: kararlılık göstergesinin dolması, elle beslenen bant dışı
bir okumanın hem AYKIRI işaretlenmesi hem tolerans sayacını artırması, hedefe
ulaşınca kaydın durup **oturumun açık kalması**, grafiğin PNG olarak
yazılması, dışlamanın geri alınması ve panoya kopyalama, onay kuyruğunun
sorguyla örtüşmesi + onay ve geri çevirme, tarih aralığı süzgecinin (hazır,
özel, ters girilmiş aralık) hem oturumlarda hem sertifikalarda çalışması,
yetki matrisinin dolması, denetim CSV'sinin **tüm** satırları hash sütunlarıyla
yazması, yedeğin diske düşüp durum çubuğuna yansıması ve bildirimden ilgili
sayfaya gidilmesi.

Ayrıca **yerleşim nöbetleri**: pencere 1920×1080'e sığmalı, hiçbir sayfa
gövdeden uzun olmamalı, uzun sayfa kaydırılabilir kalmalı, giriş kutusu ve
tablo satırı metni **kırpmayacak** kadar yüksek ama gereksiz cömert de
olmamalı, yazı %150'ye büyütüldüğünde satır yüksekliği de büyümeli. Kırpılma
kullanıcının bildirdiği gerçek bir hataydı; nöbet onun tekrarlamasını
engelliyor.

Ölçüm planı için: planın veritabanına doğru sırayla yazılması, plan panelinin
yalnızca çok noktalı oturumda görünmesi, "Sonraki nokta"da istatistiğin
sıfırlanması ve simülasyonun yeni noktanın nominaline geçmesi, okumaların üç
noktaya **sahipsiz kalmadan** dağılması, sertifikada üç ayrı nokta bölümü
oluşması ve geçmiş detayında üç blok görünmesi. Ayrıca Qt'siz tarafta:
sahipsiz (`point_id IS NULL`) okumaların ilk noktaya sayılması, bir nokta bile
uygunsuzken belgenin uygunsuz çıkması, plansız oturuma tek noktalı planın
kendiliğinden kurulması ve ikinci çağrının yeni nokta açmaması.

Şablon, tercih, dil ve arama için: aynı adla kaydetmenin üzerine yazması ve
ikinci satır açmaması, boş plan/adsız şablonun reddedilmesi, tercihin
kullanıcıya yazılıp diğerini etkilememesi, yazı boyutu çarpanının stil
sayfasını gerçekten ölçeklemesi (ve 1.0'da hiç dokunmaması), İngilizce
sertifikada bölüm başlıklarının ve sonuç metninin çevrilmesi, katalogda
olmayan metnin aynen kalması, aramanın tek karakterde çalışmaması ve
sonuçların tür sırasına göre gelmesi.

---

---

## Dosya düzeni

```
callog/
├── qt.py               Qt bağlama katmanı (PySide6)
├── theme.py            Palet + stil sayfası, beyaz/koyu tema
├── pdffont.py          PDF için Türkçe karakter destekli font kaydı
├── db.py               SQLite şeması, değişmezlik tetikleyicileri, göç
├── audit.py            Denetim kaydı, SHA-256 hash zinciri
├── auth.py             Kullanıcı, pbkdf2 parola hash'i
├── perms.py            Rol → yetki tablosu ve ekran matrisi, tek doğruluk kaynağı
├── prefs.py            Kişi bazlı tercihler (tema, yazı boyutu, dil)
├── i18n.py             TR/EN katalog; belgeler tam, arayüz kısmen çevrili
├── stats.py            Welford ortalama/std/u(A), uygunluk kriteri — Qt'siz
├── points.py           Ölçüm planı: nokta başına istatistik ve karar — Qt'siz
├── templates.py        Ölçüm şablonları (nokta planı + periyot) — Qt'siz
├── search.py           Genel arama: cihaz/oturum/sertifika/seri — Qt'siz
├── stability.py        Kararlılık durumu, aykırı okuma tespiti — Qt'siz
├── trend.py            Sürüklenme eğilimi, sınır aşım tahmini — Qt'siz
├── notifications.py    Bildirim merkezi: dikkat isteyenlerin tek listesi
├── backup.py           SQLite yedekleme API'siyle kopya, yedek yaşı, budama
├── acquisition.py      QThread okuma döngüsü
├── certificate.py      Sertifika hesabı, PDF + DOCX üretimi, onay ve silme;
│                       oturum ve dalga serisi sertifikaları tek defterde
├── documents.py        Cihaza iliştirilen belgeler, cihaz özeti, seyir serisi
├── sessions.py         Oturum adlandırma ve yumuşak silme
├── waveform.py         Dalga yakalama: CSV yazımı, künye, SHA-256 doğrulama
├── testmodes.py        Test modları: cihaz ayarı + zincir + çözümleme
├── defib.py            Şok çözümlemesi: faz, tepe, eğim, τ, enerji — Qt'siz
├── shockreport.py      Şok raporu PDF: dalga grafiği + cihaz ekran görüntüsü
├── seriesreport.py     Seri şok raporu PDF: bindirmeli grafik + ortalama
│                       dalga, istatistik (s, u, U), uygunluk kararı,
│                       ölçüm ölçüm tablo; sertifika defterine işler
├── chart.py            Sertifika ölçüm grafiği (vektör, Qt'siz)
├── drivers/
│   ├── base.py         Sürücü arayüzü
│   ├── fluke8846a.py   Fluke 8846A SCPI sürücüsü
│   ├── keysight_dsox1202a.py  DSOX1202A: skaler ölçüm + dalga yakalama
│   ├── simulated.py    Simülasyon multimetre
│   ├── simulated_scope.py     Simülasyon osiloskop
│   ├── discovery.py    VISA tarama + *IDN? eşleştirme
│   └── __init__.py     REGISTRY — yeni cihaz buraya eklenir
└── ui/
    ├── login.py        Giriş, kullanıcı oluşturma
    ├── setup_page.py   DUT (yeni + geçmiş) · cihaz bağlantısı · ölçüm ayarları
    ├── acquire_page.py Canlı ölçüm: grafik, kararlılık, ölçüm planı
    ├── waveform_page.py Dalga yakalama: tetikleme, CSV, yakalama listesi
    ├── approvals_page.py Onay kuyruğu: ölçüm özeti + grafik yan yana
    ├── search_dialog.py Genel arama penceresi (Ctrl+K)
    ├── compare_dialog.py Oturum karşılaştırma: bindirmeli okuma grafiği
    ├── pdf_preview.py  Uygulama içi PDF önizlemesi (QtPdf)
    ├── history_page.py Oturumlar + sertifikalar, filtreler, PDF/DOCX/XLSX
    ├── devices_page.py Cihazlar defteri: geçmiş, seyir + eğilim, belgeler
    ├── admin_page.py   Kullanıcılar, referans cihazlar, yetki matrisi, denetim
    ├── nav.py          Sol gezinme şeridi, kullanıcı kartı, rol rozeti
    ├── icons.py        Kod içinde çizilen tema uyumlu simgeler
    ├── util.py         Tablo yerleşimi, boş durum kaplaması, tarih süzgeci
    └── main_window.py  Gezinme, menü çubuğu, ana ekran, bildirimler, yedek
```

---

## Tasarım kuralları

**Arayüz katmanı cihazla veya veritabanıyla doğrudan konuşmaz.** Her şey servis
katmanı üzerinden geçer. Bu kural bozulursa test yazılamaz ve simülasyon modu çalışmaz.

**VISA çağrıları asla ana iş parçacığında yapılmaz.** `inst.query()` saniyelerce
bloklayabilir ve arayüz donar. Okuma `AcquisitionWorker` (QThread) içinde yapılır,
sonuç Qt sinyaliyle arayüze gider.

**Her okumada tek tek INSERT atılmaz.** Okumalar tamponda birikir, saniyede bir
toplu yazılır.

**Ham veri silinmez.** `readings` tablosunda UPDATE ve DELETE tetikleyicilerle
engellenmiştir. Aykırı değer `reading_exclusions` tablosunda gerekçesiyle işaretlenir,
sertifika hesabından çıkarılır ama kayıtta kalır.

**Grafik renkleri palete bağlı değil.** pyqtgraph Qt paletini kullanmaz; tema
değişiminde `AcquirePage.apply_plot_theme()` elle çağrılır.

**Sayfa ekrandan uzunsa kaydırılır, sıkıştırılmaz.** Qt, düzenin sığmadığı
durumda widget'ları en az boyutlarının altına indiriyor: metin kutuların
içinde kırpılıyor, tablo satırları yarım görünüyor. Yeni bir kutu eklerken
sayfanın toplam yüksekliği ekranı aşıyorsa `util.scroll_body()` kullanılır.
Sabit piksel yüksekliği verilen her yer (`setMaximumHeight`) yazı boyutu
büyütüldüğünde kırpma riski taşır; tablo satır yüksekliği bu yüzden
`util.compact_rows()` içinde yazı ölçüsünden hesaplanıyor.

**Hatalar görünür olmalı.** Uygulama `pythonw.exe` ile açıldığında konsol yoktur;
yakalanmamış bir hata izsiz kaybolur ve kullanıcıya "düğmeye bastım hiçbir şey
olmadı" gibi görünür. `run.py` bir `sys.excepthook` kurar ve hatayı pencerede
gösterir. Ayrıca tek örnek kilidi (`QLockFile`) ikinci bir kopyanın aynı
veritabanına yazmasını engeller, SQLite `busy_timeout` 5 sn'dir.

