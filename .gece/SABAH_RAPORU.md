# Sabah raporu — canlıya hazırlık gecesi (2026-10-19)

> Gece çalışması 02:10 civarında bitti. Son durum: **1261 test geçiyor, 2 xfail** (ikisi de bilinçli
> açık bırakıldı, aşağıda) · `ruff` temiz · `mypy src` temiz · dal `gece/arayuz-guvenlik` GitHub'a
> push edildi (https://github.com/berkcicekk/synora). `main`'e birleştirme yapılmadı.

## 1. Tek bakışta

Onayladığınız planın (Faz 1 + Faz 2) tamamı bitti. Kod tarafında canlıya çıkışın önünde bildiğim engel
yok; kalanlar **sizin kararınız ya da dış iş** (bkz. §4). Her madde önce test, sonra kod; her biri ayrı
commit, hepsi sizin adınıza (Claude ortak yazar satırı yok).

## 2. Ne yapıldı

**Güvenlik ve güvenilirlik (korumalı web/iş yürütücü kodu, onayınızla)**
- **Ö9 veritabanı yarışı** — işlerin "denetleniyor"da takılıp kalması ve ara sıra yanlış 404 bitti; testteki
  geçici ara katman kaldırıldı.
- **Üretim ayar denetimi** — https olmayan adres, eksik SMTP, `.local` gönderici, boş alan adı listesi ya da
  bulunamayan kılavuzla uygulama **başlamaz**; üretimde e-posta artık konsola düşmez. Unutulmuş
  `SYNORA_DEV=1` reddedilir.
- **Giriş bağlantısı sızıntısı** — uvicorn erişim kaydı `/auth?token=…` yazıyordu (15 dk giriş anahtarı);
  üretimde kapalı. Uygulama olayları artık gerçekten kaydediliyor (önceden atılıyordu).
- **E-posta** — gönderim sunucuyu kilitlemiyor; SMTP hatası 500 yerine "E-posta gönderilemedi" mesajı.
- **Ö6 kaynak sınırları** — kopya üretimi eşzamanlı sınıra sayılıyor, sunucu genelinde sınırlı, kuyruk
  sınırlı; paralel isteklerle sınır aşılamıyor.
- **Ö8** — 24 saati geçen rapor temizlik görevini beklemeden kapanıyor; silinen veri WAL'da kalmıyor.
- **Ö3** — bilinmeyen adres/yanlış yöntem düzgün sayfa; beklenmeyen hata güvenlik başlıklı 500 sayfası,
  ayrıntı kayda bile gitmiyor; arayüze giden hatalar Türkçe.
- **Ö5** — günlük sınır rapor silinerek aşılamıyor (yalnızca yeni yüklemeyi sayar).
- **Gövde sınırları** — oturumsuz formlardan disk doldurulamıyor (çok parçalı gövde Starlette'te diske
  yazılıyordu).
- **İşletim** — gerçek `/health`, bozuk kılavuz dosyası açılışı çökertmiyor, statik dosya önbelleği.
- **Kayıt onayı** — onay kutusunu adres sahibi bağlantının onay sayfasında işaretliyor (başkası sizin
  adresinizle kayıt formunu doldurursa sizin adınıza onay oluşmuyor).

**Arayüz (UI/UX Pro Max kurallarıyla denetlendi)**
- Rapor: özet ve süzgeç sayıları artık aynı (bulgu); telefonda karta dokununca sayfa sıçramıyor; yatay
  telefonda tek sütun; paragraf türü seçimi telefonda büyük; silmede "Vazgeç".
- İşleniyor ekranı oturum düşünce sonsuza dek beklemiyor.
- Yükleme: dokunmatikte "dokunun" metni, kısa alan, düğme ilk ekranda.
- Formlar: hata alana bağlı; aydınlatma metni yeni sekmede (yazdığınız adres kaybolmaz).
- Kontrast ve dokunma alanları düzeltildi (yer tutucu, kenarlıklar, gizlilik anlatısı, küçük bağlantılar).

**Dağıtım** — `deploy/`: systemd birimi, nginx yapılandırması (tezin diske yazılmaması için tampon kapalı,
sorgu dizesiz kayıt, giriş/kayıt için IP sınırı), ortam değişkenleri örneği, kurulum notu.

**Bağımsız gözden geçirme** — gece sonunda tüm değişiklikleri ayrı bir ajanla gözden geçirttim; bulduğu
7 sorunun hepsi düzeltildi (günlük sınırın kopya indirmeyi engellemesi, başkası adına onay, 500 iz kaydı,
405 Allow başlığı, nginx sürüm uyumu, kampüs NAT'ında hız sınırı, kurulum izinleri).

## 3. Testlerde değiştirdiklerim (beklenti gevşetilmedi)

Onaylı davranış değişikliği yüzünden şu testlerin **kurulumu** ya da hedefi değişti; hiçbir güvenlik
denetimi gevşetilmedi:
- Giriş öncesi CSRF anahtarı artık `/giris` sayfasından alınıyor (ana sayfada form yok).
- Güvenlik testlerindeki üretim fikstürüne SMTP ayarı eklendi (artık zorunlu).
- Telefon düzeni testi, genişletilmiş medya sorgusunu buluyor (kurallar aynı).
- İki kayıt testi, onay kutusunun onay sayfasında da işaretlenmesini bekliyor (gözden geçirmede bulunan
  açığın düzeltmesi).
- Beş xfail (Ö3, Ö5, Ö6, Ö8, Ö9) gerçek teste dönüştü ve geçiyor.

## 4. Sizi bekleyenler (kod dışı)

1. **Aydınlatma metni** — `/aydinlatma` taslak; veri sorumlusu, başvuru yolu, barındırma yeri boş.
   Kesinleşince `TERMS_VERSION` artırılmalı. Pilotun tek gerçek engeli bu.
2. **SMTP sağlayıcısı** — giriş e-postaları için; gerçek sunucuyla hiç denenmedi.
3. **Barındırma** — Linux sunucu (Windows'ta iş yürütücünün bellek sınırı çalışmaz). Kurulum `deploy/README.md`.
4. **Yedekleme politikası** — kalıcı veri yalnızca kayıt onayları.
5. **Word'de elle açılış testi** — düzeltilmiş/yorumlu kopya LibreOffice'te otomatik test ediliyor.
6. **`main`'e birleştirme** — tüm iş `gece/arayuz-guvenlik` dalında; isterseniz birleştiririm.

Bilinçli açık bırakılanlar: **Ö7** uygulama içi IP sınırı (ilk katmanı nginx'te), **Ö4** gömülü belge
uyarısı ve **Ö1/Ö2** (yeni özellikler) — canlıya çıkış için gerekmiyor.

## 5. Nasıl bakılır

- Geliştirme sunucusu açık: http://127.0.0.1:8765 (giriş için `/giris`, bağlantı konsol kaydına düşer).
- Commit listesi: `git log --oneline dc01dc4..HEAD` (bu gecenin ve dünkü giriş/kayıt işinin tamamı).

---

# Sabah raporu — gece/arayuz-guvenlik (2026-10-18)

> Durum: **son**. Gece çalışması 02:26'da bitti. 05:33'teki son kontrol bilgisayar uykudayken kaçtı;
> kullanıcı dönünce onayıyla yapıldı: 401 passed, 7 xfailed · ruff temiz · mypy temiz · `src/**/*.py`
> ve `rulesets/` için `git diff` boş.

## 1. Tek bakışta

- **Dal:** `gece/arayuz-guvenlik` (main'den). 19 commit, push/merge yok, main'e dokunulmadı.
- **Testler:** başlangıçta 306 geçiyordu → şimdi **401 geçiyor + 7 xfail** (xfail'ler bilinen açıklar,
  gerekçeli). `ruff` ve `mypy src` temiz.
- **Korumalı modüllerde kod değişikliği yok.** `src/**/*.py` ve `rulesets/` için `git diff` boş.
  Değişenler: şablonlar, `app.css`, `app.js`, testler ve `.gece/`.
- **En önemli bulgu (sizin kararınız gerekiyor):** A9 veritabanında **eşzamanlılık hatası (Ö9)**. İş
  yürütücü ile istek aynı anda okuyunca bir iş sonsuza dek "denetleniyor"da kalabiliyor, ara sıra 500
  çıkıyor. Pilotta birden çok öğrenci aynı anda yüklerse görülür. Düzeltme tek fonksiyon (ONERILER Ö9).
  Gece test takımı bu yüzden rastgele kırmızıya dönüyordu; test ortamına **geçici** bir ara katman
  ekledim (aşağıda §4).

## 2. Ne yapıldı

### Faz 1 — Rakip analizi → `RAKIP_ANALIZI.md`
Türkiye'de enstitülerin kullandığı otomatik bir .docx biçim denetim aracı bulamadım. Süreç her yerde
kontrol formu + görevli + Word yorum kutuları. Yurt dışında en yakın örnek UCSD'nin 2026 pilotu
(üç kovalı sonuç). 11 somut fikir çıkardım; 8'ini bu gece uyguladım, 2'si backend gerektiriyor
(ONERILER Ö1–Ö2), biri şablon .docx bekliyor (SORULAR #11).

### Faz 2 — Arayüz
- **Akış netliği:** Yükle → Denetim → Rapor → Kopya adım göstergesi (yükleme, işleniyor ve hata
  ekranlarında).
- **Rapor:** üç kovalı özet (Otomatik düzeltilebilir / Sizin düzeltmeniz gereken / Kontrol edin;
  tıklayınca süzgeç uygulanıyor), "Sıradaki adımlar" listesi, yeni **Elle** süzgeci, her bulguda
  **"Word'de nasıl düzeltilir"** (kural ailesine göre Türkçe Word menü yolu), düzeltilebilir bulgularda
  not.
- **Güven:** yükleme alanının altında üç güvence (mimari §10.1'in istediği gizlilik notu artık yükleme
  ekranında), "Yüklemeden önce" kontrol listesi, rapor altında ve altbilgide "son onay fakültenizde"
  notu (metni siz onaylayın, SORULAR #10).
- **Hata ve boş durumlar:** başarısız denetimde hata koduna göre adım adım ne yapılacağı. Hata
  sayfasında türüne göre başlık (bulunamadı / oturum / genel) ve öneriler. Belirsiz paragraf varken
  yanıltıcı "Tebrikler" kaldırıldı. Bulgu yokken boş kovalar gizli.
- **Mobil:** rapor sayfasında **önceden var olan bir taşma hatası** düzeltildi: telefonda kopya
  düğmeleri başlığın üstüne biniyordu. Telefonda artık özet ve bulgular önce, sayfa görünümü sonra
  geliyor; yoruma dokununca sayfa kayıyor. Dar ekranda adım göstergesi tek satır.
- **Erişilebilirlik:** tanıtım sayfasının açık bölümlerinde odak çerçevesi görünmüyordu (camgöbeği
  fildişi üstünde 1,55:1) → düzeltildi. Yer tutucu metin 2,68 → 4,66:1. Rapor sayfasına `<h1>`.
  Kopya paneli `aria-expanded`, kapanınca odak geri dönüyor. Dosya alanı açıklamaya bağlı. JavaScript
  kapalıysa uyarı. WCAG kontrast oranları artık testte CSS tokenlarından hesaplanıyor.
- **Ek:** rapor yazdırma görünümü (danışmana götürülecek kontrol listesi gibi). Büyük dosyalarda
  yükleme yüzdesi (XHR).

### Faz 3 — Güvenlik → `GUVENLIK_RAPORU.md`
54 yeni güvenlik testi (A1: 26, web: 28) ve 6 belgelenmiş bulgu. **Kritik güvenlik açığı yok.** XXE
(UTF-7/EBCDIC/UTF-16 hileleri dahil), zip bombası, iç içe zip, yol aşımı, makro/şablon türleri,
başkasının işine erişim, CSRF, oturum, başlıklar ve çerez bayrakları testlerde tuttu.

| Bulgu | Önem | Öneri |
|---|---|---|
| G0 Veritabanı okuma yarışı: takılı işler, 500 | **Orta–Yüksek** (güvenilirlik) | Ö9 |
| G1 Kopya üretiminde eşzamanlılık/günlük sınır yok → bellek DoS | Orta | Ö6 |
| G2 Günlük sınır rapor silinerek aşılıyor | Düşük–Orta | Ö5 |
| G3 Giriş isteği sınırı yalnızca e-posta başına | Düşük–Orta | Ö7 |
| G4 Süresi dolan rapor temizliğe kadar (≤10 dk) açık | Düşük | Ö8 |
| G5 altChunk için mimari §8'in istediği uyarı yok | Düşük | Ö4 |
| G6 Bilinmeyen adres ham JSON döndürüyor | Bilgi/UX | Ö3 |

### Faz 4 — Arayüz testi
Her sayfada `lang`, tek `<h1>`, `<main>`, "içeriğe geç" bağlantısı, ayırt edici `<title>` ve etiketli form
alanları testle doğrulanıyor. `app.js`'in kullandığı her `id` ve `data-*` şablonlarda var. Uçtan uca
öğrenci akışı tek testte: giriş → yükle → rol seç → yeniden denetle → iki kopya → sil → çıkış.
Ekran görüntüleri: Chrome eklentisi bağlı olmadığı için headless Edge ile 1366 px ve 375 px.

## 3. Sizin bakmanız gerekenler (öncelik sırasıyla)

1. **Ö9'u onaylayın** (veritabanı yarışı). Düzeltmeden sonra `tests/web/conftest.py` içindeki
   `_serialize_db_reads` ara katmanını silin.
2. **Ö6** (kopya üretimine sınır), **Ö3** (bilinmeyen adres; tek satır). İkisi de A9 backend, plan +
   onay gerekiyor.
3. **SORULAR.md:** özellikle #10 ("son onay" ifadesi) ve önceden açık olan kapsam/KVKK/barındırma.
4. **Gerçek tarayıcıda elle bakılacaklar:** yükleme yüzdesi (XHR; headless'ta dosya seçilemediği için
  tarayıcıda denenmedi), telefonda rapor sayfası, klavyeyle rapor sayfasında gezinme.

## 4. Bilmeniz gereken bir karar: test ortamı ara katmanı

Web testleri, backend'deki Ö9 yarışı yüzünden yaklaşık 4 çalıştırmada 1 rastgele kırmızıya dönüyordu.
Bu, gece eklediğim testlerden önce de olabilen bir durum; daha çok iş çalıştıran testlerle sıklaştı.
"Kırmızı testle commit yok" kuralı ve korumalı modül kuralı birlikte uygulanınca iki seçenek kalıyordu:
backend'i değiştirmek (yasak) ya da test ortamında yarışı kapatmak. İkincisini seçtim:

- `tests/web/conftest.py` → `_serialize_db_reads`: yalnızca testlerde `Database.execute`'u, sonucu kilit
  içinde okuyan sürümle değiştiriyor. Bu, Ö9'da önerilen düzeltmenin birebir aynısı.
- Gerçek davranış ara katmansız olarak `tests/unit/test_db_concurrency.py`'de xfail ile izleniyor.
  Olasılıksal olduğu için strict değil.
- Bunu istemezseniz ara katmanı silmek yeterli; o zaman web testleri ara sıra kırmızı olur.
- Ara katmanla tam takım 6/6 çalıştırmada yeşil.

## 5. Nasıl incelenir

```bash
git log --oneline main..gece/arayuz-guvenlik
git diff main..gece/arayuz-guvenlik -- src/synora/web/templates src/synora/web/static
python -m uv run pytest -q          # 401 passed, 7 xfailed
python -m uv run pytest -q -rxX     # xfail gerekçeleri
python -m uv run synora serve --dev # arayüzü elle görmek için
```

Push etmedim. Yerel depoda remote yok; GitHub adresini (SORULAR #8) siz ekleyip dalı gönderebilirsiniz.
