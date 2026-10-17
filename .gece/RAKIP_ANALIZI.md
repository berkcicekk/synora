# Rakip analizi — tez / belge biçim denetimi

> Hazırlayan: Claude (gece modu, 2026-10-18 01:45–02:05). Kaynaklar web araması ve kamuya açık sayfalar;
> ürünlerin içine girilmedi, deneme hesabı açılmadı. Fikir alındı; metin, tasarım ve logo kopyalanmadı.

## 1. Kısa sonuç

- **Türkiye'de enstitülerin kullandığı otomatik bir .docx biçim denetim aracı bulamadım.** Süreç her yerde
  aynı: öğrenci ve danışman **kontrol formu** dolduruyor, enstitü görevlisi Word dosyasını **elle**
  kontrol ediyor, hataları **açıklama kutularıyla** işaretleyip tezi geri gönderiyor. Bulduğum otomatik
  çözümler biçimi kontrol etmiyor, baştan doğru biçimde üretiyor: Overleaf/LaTeX şablonları (Erciyes,
  ESOGÜ, İstanbul Ü.).
- **Yurt dışında en yakın rakip UC San Diego'nun "Dissertation Formatter" pilotu (2026).** .docx alıyor,
  84 kuralı denetliyor, 17'den fazla düzeltmeyi otomatik yapıyor ve sonuçları **üç kovaya** ayırıyor:
  düzeltildi / sizin yapmanız gereken / kontrol edin. Aynı kurumda kullanılıyor; satılan bir ürün değil.
- Ticari araçlar (PerfectIt, Paperpal Preflight, DocValidator, Reformat) **ya dil ve tutarlılık
  denetliyor** (yazım, kısaltma, büyük harf) **ya da genel yayın öncesi kontroller yapıyor**. Bir
  enstitünün kılavuzunu madde madde uygulayan, Türkçe çalışan bir araç yok.
- Akademik prototipler var: Boğaziçi lisans projesi (LaTeX/PDF, 2022), UNM Endonezya (web, yazı tipi,
  kenar boşluğu ve başlık), IPB Endonezya (Word 2007 eklentisi, 2011). Hiçbiri yaygınlaşmamış ve hiçbiri
  metnin korunduğunu kanıtlamıyor.

**Sonuç:** Synora'nın Türkiye'de doğrudan bir rakibi yok. Asıl "rakip" bugünkü elle kontrol süreci
(form + görevli + yorum kutuları). Synora bu süreci **öğrencinin teslimden önce kendi başına
yapabileceği** hale getiriyor. Yorumlu kopya, görevlinin bugün elle yaptığı işin otomatik karşılığı.

## 2. Kim var, ne yapıyor

| Araç / süreç | Tür | Girdi | Ne yapıyor | Arayüzde iyi olan | Zayıf yanı |
|---|---|---|---|---|---|
| **UCSD Dissertation Formatter** (pilot, 2026) | Kurum içi web aracı | .docx | 84 kural / 13 kategori, 17+ otomatik düzeltme | Sonuçlar **Düzeltildi / Yapılacak / Kontrol et** diye ayrılıyor; her bulguda "ne değişti, neden" var; "resmi incelemenin yerini almaz" uyarısı | Gizlilik ve saklama açıklanmıyor ("onaylı servis kontrolleri" deniyor) |
| **Türk enstitüleri** (Ankara Adli Bilimler, Sakarya Eğitim, Işık, ADÜ…) | Elle kontrol | Word/PDF + form | Kontrol formu (punto, satır aralığı, kenar boşluğu…), görevli denetimi, uygun değilse geri gönderme | Görevli hataları **metin üzerinde açıklama kutularıyla** işaretliyor; öğrenci, danışman ve enstitü sırayla imzalıyor | Yavaş, tekrarlı, görevliye bağımlı; öğrenci hatayı teslimden sonra öğreniyor |
| **Boğaziçi FBE** | Elle + liste | PDF + imzalı kontrol listesi | E-postayla "çevrimiçi biçim kontrolü" | "Sık yapılan hatalar" listesi; LaTeX şablonu | Otomatik değil (2022'deki lisans projesi LaTeX/PDF içindi) |
| **LaTeX şablonları** (Erciyes, ESOGÜ, İÜ, Overleaf) | Şablon | — | Biçimi baştan doğru üretiyor | Kılavuza uygunluk "baştan" sağlanıyor | Tıp ve sosyal bilimlerde öğrenciler Word kullanıyor; sonradan yapılan değişiklikleri denetlemiyor |
| **ASU format tool** | Şablon üretici | Form | Word/LaTeX şablonu üretiyor | Basit sihirbaz | Denetim yok |
| **PerfectIt** | Word eklentisi (ücretli) | Word | Tutarlılık: kısaltma, büyük harf, tire, madde işaretleri; kurum stil rehberi tanımlanabiliyor | Bulgu → düzelt / atla / kurala çevir; Word içinde çalışıyor | Sayfa düzeni ve kılavuz ölçüleri yok; elle çalıştırılıyor; Türkçe stil rehberi yok |
| **Paperpal Preflight** | Web (makale) | Makale | 30+ hazırlık kontrolü (dil, teknik, biçim, intihal); ücretsiz rapor | **"Hazırlık raporu"**: hangi alan uygun, hangisi çalışma istiyor | Dergiye yönelik; metni yapay zekâya veriyor |
| **Word Erişilebilirlik Denetçisi** | Word'e yerleşik | Word | Hata / Uyarı / İpucu | Bulguya tıklayınca belgede ilgili yere gidiyor; her bulguda **"Neden düzeltmeli"** ve **"Nasıl düzeltilir"** var; önerilen eylemler | Biçim kılavuzu yok |
| **DocValidator / Reformat** (AppSource) | Word eklentisi | Word | Boş paragraf, elle sayfa sonu, düşük çözünürlüklü görsel; şablona göre yeniden biçimleme | Tek tıkla şablon uygulama | Genel amaçlı; kılavuz ve metin koruma garantisi yok |
| **UNM (Endonezya)** / **IPB (Endonezya)** | Akademik prototip | .docx / .doc | Yazı tipi, kenar boşluğu, aralık, başlık yapısı | — | Elle yükleme, kurum sistemiyle bağlantı yok; yaygınlaşmamış |

## 3. Synora'nın farkı

1. **Metin dokunulmazlığı kanıtlanıyor.** Rakiplerin hiçbiri bunu söz olarak bile vermiyor. Synora her
   çıktıda `content_fingerprint` ile doğruluyor; doğrulanamazsa dosya üretmiyor. Bu, pazarlamanın merkezine
   konacak kadar güçlü.
2. **Yapay zekâ metni görmüyor.** Paperpal gibi araçlar metni modele gönderiyor. UCSD gizliliği açıklamıyor.
   Synora'da sınıflandırıcı yalnızca sayısal özellik alıyor. KVKK ve tez gizliliği için belirleyici bir fark.
3. **Dosya saklanmıyor.** Yalnızca SHA-256 özeti tutuluyor, rapor 24 saatte siliniyor.
4. **Kılavuz kural setine çevrilmiş** (YAML, madde madde eşleme ve çelişki notları). Fakülte veya enstitü
   değişince kod değişmiyor.
5. **Düzeltme Word'ün kendi aracıyla geliyor** (izlenen değişiklik). Öğrenci her değişikliği görüp kabul
   ediyor. UCSD düzeltmeyi doğrudan yapıyor.
6. **Yorumlu kopya**, Türk enstitülerinde görevlinin elle yaptığı işin (açıklama kutuları) aynısı. Öğrenciye
   tanıdık bir çıktı.
7. **Türkçe ve yerel.** Ondalık virgül, Türkçe başlık harfi kuralları, ZBEÜ kılavuzu.

## 4. Synora için alınacak somut fikirler

Her fikirde: kaynağı, Synora'da nerede uygulanacağı ve korumalı modül gerekip gerekmediği. ✅ = bu gece
yalnızca şablon/CSS/JS ile yapılabilir. 🔒 = backend gerekir, ONERILER.md'ye yazılır.

1. **Sonuçları üç kovada özetle** (UCSD). Rapor ekranının başında üç kutu: **"Otomatik düzeltilebilir"**
   (düzeltilmiş kopyada gelir), **"Sizin düzeltmeniz gereken"** (yorumlu kopyada gelir), **"Kontrol
   edin"** (türü belirsiz paragraflar ve kapak gibi denetlenmeyen kısımlar). Her kutu ilgili çıktıya ya da
   süzgece bağlanır. Veri zaten raporda var (`fixable`, `errors+warnings`, `unknown_paragraphs`). ✅
2. **"Word'de nasıl düzeltilir"** (Word Erişilebilirlik Denetçisi). Otomatik düzeltilemeyen her bulgu
   kartına Word menü yolu: "Giriş › Paragraf › Satır aralığı" gibi. Mimari §10.1 madde 4 bunu zaten
   istiyor. Kural kimliğine göre şablonda bir eşleme tablosu yeterli. ✅
3. **"Önce hataları düzeltin" yönlendirmesi ve sıradaki adım kutusu** (Word denetçisi + Paperpal hazırlık
   raporu). Raporun en üstünde tek cümle: "1) Düzeltilmiş kopyayı indirip Word'de kabul edin,
   2) kalan N bulguyu yorumlu kopyayla düzeltin, 3) yeniden denetleyin." Akışı çok netleştirir. ✅
4. **Adım göstergesi: Yükle → Denetim → Rapor → Kopya.** Yükleme, işleniyor ve rapor ekranlarında aynı
   dört adımlı gösterge, öğrenci nerede olduğunu her zaman bilir. ✅
5. **"Resmi kontrolün yerini almaz" notu** (UCSD). Rapor altında ve tanıtım sayfasında: "Synora enstitü
   biçim kontrolünden önce kendi denetiminiz içindir; son onay enstitünündür." Yanlış beklentiyi ve
   sorumluluk riskini azaltır. Metin önerisi; nihai ifade için SORULAR'a da not. ✅
6. **Gizlilik notu yükleme alanının hemen yanında** (UCSD'nin zayıf yanından ders). Mimari §10.1 madde 1
   yükleme ekranında gizlilik notu istiyor. Şu an not yalnızca altbilgide. ✅
7. **Yüklemeden önce kısa kontrol listesi** (Boğaziçi "sık yapılan hatalar"). ".doc ise .docx olarak
   kaydedin · parola korumasını kaldırın · izlenen değişiklikleri kabul edin" gibi. Başarısız yükleme
   sayısını azaltır. ✅
8. **Hata ekranlarında "ne yapabilirim" listesi.** Rakiplerin hiçbiri bunu iyi yapmıyor. Dosya
   reddedildiğinde kod + insan dili + 2–3 somut adım (Word'de aç › Farklı kaydet › .docx). ✅
9. **"Bu bulgu yanlış mı?" geri bildirimi** (UCSD "yanlış bulgu" ölçüyor). Metin göndermeden yalnızca
   `rule_id` + `para_id` + işaret. Pilot kalitesini ölçmek için önemli. 🔒 (yeni route + DB alanı)
10. **Kılavuz kontrol listesi görünümü** (Türk enstitü formları). Raporda "Denetlenen maddeler" listesi:
    her kılavuz maddesi için ✓ uygun / ✗ bulgu var / — denetlenmedi. Enstitü formunun dijital karşılığı
    olur, danışmana gösterilebilir. Kısmen ✅ (kural seti şablona geliyor), tam hali 🔒 (geçen kuralların
    listesi raporda yok).
11. **Resmi şablon .docx indirme** (ASU, Erciyes). "Baştan doğru başla" seçeneği. Fakülteden şablon
    gerekir → SORULAR. ⛔

## 5. Bu gece uygulanacaklar (Faz 2)

Sırayla 6 (gizlilik notu), 4 (adım göstergesi), 1 (üç kova), 3 (sıradaki adım), 2 (Word'de nasıl
düzeltilir), 8 (hata ekranları), 7 (yükleme öncesi liste), 5 (resmi kontrol notu). 9 ve 10 ONERILER.md'ye.

## Kaynaklar

- UCSD Dissertation Formatter — https://tritonai.ucsd.edu/use-cases/dissertation-formatter.html
- Boğaziçi lisans projesi — https://seniorprojects.cmpe.bogazici.edu.tr/semesters/2022-fall/a-format-checking-software-for-the-theses-of-boun-grad-students/
- Boğaziçi FBE kontrol listesi — https://fbe.bogazici.edu.tr/en/announcements/thesis-format-checklist/2937
- Ankara Ü. Adli Bilimler kontrol formu — https://adlibilimler.ankara.edu.tr/wp-content/uploads/sites/58/2026/02/ABE_Temsilci_Tez_Yazim_Kontrol_formu.docx
- Sakarya Ü. savunma sonrası süreç — https://egitim.sakarya.edu.tr/sites/egitim.sakarya.edu.tr/formlar/Tez_Savunmasi_Sonrasi_islem_Surecleri%20(1).pdf
- Işık Ü. tez kontrol formu — https://isikun.edu.tr/sites/default/files/2024-10/14282_1_lee2_tez_proje_kontrol_formu.pdf
- Overleaf Türkçe şablonlar — https://www.overleaf.com/latex/templates/tagged/turkish
- ASU format tool — https://graduate.asu.edu/sites/default/files/how-to-use-online-format-tool.pdf
- UNM (Endonezya) — https://journal.unm.ac.id/index.php/JESSI/article/view/9211
- IPB (Endonezya) — https://repository.ipb.ac.id/handle/123456789/64501
- PerfectIt stil rehberi — https://intelligentediting.com/support/faqs/how-do-i-use-perfectit-to-enforce-my-companys-style-guide/
- Paperpal Preflight — https://cactusglobal.com/?p=7623
- Word Erişilebilirlik Denetçisi kuralları — https://support.microsoft.com/en-gb/accessibility/office-accessibility/rules-for-the-accessibility-checker
- Word eklentisi örneği (Reformat) — https://appsource.microsoft.com/en-us/product/office/wa200007463
- DocValidator — https://platform.softwareone.com/product/docvalidator/PCP-1746-1359
