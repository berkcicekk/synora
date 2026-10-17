# Güvenlik raporu — gece taraması (2026-10-18)

> Kapsam: A1 (ingest, xmlsafe) ve A9 web (giriş, oturum, CSRF, yetki, yükleme, başlıklar, sınırlar).
> Yöntem: kod okuma + saldırı testleri. **Korumalı modüllerde kod değiştirilmedi.** Bulunan her açık
> `xfail(strict=True)` testiyle belgelendi; düzeltilince test XPASS verip kırmızıya döner, böylece
> işaretin kaldırılması unutulmaz. Çözüm önerileri: `.gece/ONERILER.md`.

## Özet

| # | Bulgu | Önem | Modül | Test (xfail) | Öneri |
|---|-------|------|-------|--------------|-------|
| G0 | Veritabanı okumalarında yarış: işler "denetleniyor"da takılı kalabiliyor, ara sıra 500/yanlış 404 (erişilebilirlik/DoS; veri sızıntısı görülmedi: satırlar tutarlı, sahiplik e-postayla denetleniyor) | **Orta–Yüksek** (güvenilirlik) | A9 db | `tests/unit/test_db_concurrency.py` (strict değil) | Ö9 |
| G1 | Kopya üretimi eşzamanlılık ve günlük sınıra tabi değil → bellek/CPU tüketimi (DoS) | **Orta** | A9 | `test_output_respects_concurrency_limit` | Ö6 |
| G2 | Günlük iş sınırı rapor silinerek aşılabiliyor | Düşük–Orta | A9 db | `test_daily_job_limit_survives_deleting_reports` | Ö5 |
| G3 | Giriş isteği sınırı yalnızca e-posta başına; tek istemci izinli alandaki tüm adreslere bağlantı yağdırabilir | Düşük–Orta | A9 | `test_login_requests_limited_per_client` | Ö7 |
| G4 | Süresi dolan rapor temizlik görevine kadar (≤10 dk) açılabiliyor; gizlilik sözüyle küçük çelişki | Düşük | A9/A10 | `test_expired_report_is_not_served_before_purge` | Ö8 |
| G5 | altChunk/gömülü OLE için mimari §8'in istediği uyarı yok; gömülü içerik denetlenmeden "temiz" rapor | Düşük | A2/A6 | `test_alt_chunk_produces_warning` | Ö4 |
| G6 | Bilinmeyen adres/yanlış yöntem ham JSON döndürüyor (bilgi sızıntısı yok, yalnızca UX) | Bilgi | A9 | `test_unknown_url_shows_friendly_page` | Ö3 |

**Kritik güvenlik açığı bulunmadı.** En önemli bulgu G0, bir güvenilirlik hatası: pilotta birden çok
öğrenci aynı anda kullanınca işler takılı kalabilir. Tez metninin sızması, dosyanın diske yazılması, XXE,
zip bombası, yol aşımı, makro, başkasının işine erişim ve CSRF'e karşı korumalar testlerde tuttu.

## Doğrulanan korumalar (testi geçen)

### A1 — Güvenli giriş (`tests/security/test_ingest_more.py`, 26 yeni test + mevcut 24)
- **XXE / entity:** UTF-7, EBCDIC (cp037), UTF-16 BOM ile gizlenmiş DOCTYPE reddediliyor. Bayt deseni
  kaçırılsa bile ikinci kapı (lxml docinfo) yakalıyor. Parametre entity reddediliyor. XInclude işlenmiyor.
- **Kaynak tüketimi:** 5000 düzey iç içe XML 5 sn'nin altında reddediliyor. Çok sayıda küçük ve yüksek
  oranlı parça toplam sınıra takılıyor. İç içe zip (gömülü nesne) hiç açılmıyor.
  - Not: libxml2 2.11, `huge_tree=False` iken 11 MB'lık tek metin düğümünü kabul ediyor. Belleği
    sınırlayan kapı part başına bayt sınırı (64 MB) ve toplam sınır (300 MB). Bu bir açık değil, ama
    "huge_tree kapalı, metin düğümü 10 MB'ı geçemez" varsayımına güvenilmemeli.
- **Yol aşımı / adlar:** Mutlak yol, sürücü harfi, ters bölü, `.`/`..`/boş segment, denetim karakteri
  reddediliyor. Adın içine NUL koyarak ikinci ad kaçırma girişimi DUPLICATE_PART ile reddediliyor
  (Python zipfile adı NUL'da kesiyor).
  - Bilgi: DEL (0x7F) karakteri part adında kabul ediliyor. Synora diske yazmadığı için etkisi yok;
    OPC dilbilgisine sıkı uyum istenirse `_check_part_name`'e eklenebilir.
- **Tür sahteciliği:** exe ve pdf → NOT_A_ZIP. .docm, .dotm ve herhangi bir yerde, herhangi bir harf
  durumunda `vbaProject.bin` → MACRO_ENABLED. .dotx ve .xlsx → NOT_DOCX.
- **Sızıntı:** Hata nesnesinde belge metni yok; lxml istisna zinciri bastırılıyor (`from None`).

### A9 — Web (`tests/web/test_web_security.py`, 28 geçen + 4 xfail)
- **Giriş bağlantısı:** Süresi dolmuş bağlantı reddediliyor. Kullanılmış bağlantı başka tarayıcıdan
  yeniden POST edilemiyor. Geçersiz bağlantı sayfası token'ı yansıtmıyor. E-postadaki bağlantı `Host`
  başlığından değil ayarlardaki `base_url`'den kuruluyor (host header injection yok). Token ve oturum
  kimliği veritabanında yalnızca hash olarak duruyor.
- **Oturum:** Süresi dolan oturum düşüyor. Çıkıştan sonra eski çerez işe yaramıyor (sunucu tarafında
  siliniyor). Çıkış CSRF istiyor.
- **CSRF ve yetki:** Silme işlemi CSRF ve sahiplik istiyor. Bir kullanıcının CSRF token'ı başkasında
  çalışmıyor. Bozuk ya da enjeksiyon denemesi içeren iş kimlikleri 404 dönüyor. Bilinmeyen kopya türü
  404/405 dönüyor. Başarısız iş için kopya ya da yeniden denetim 409 dönüyor.
- **Yükleme:** Content-Type sahteciliği etkisiz (içerik denetleniyor). Uzunluk bildirmeyen akış yüklemesi
  50 MB'ta kesiliyor (413).
- **Başlıklar:** CSP (`default-src 'self'`, `frame-ancestors 'none'`), nosniff, XFO DENY,
  Referrer-Policy no-referrer ve `Cache-Control: no-store` tüm yanıt türlerinde var: sayfa, hata, JSON
  hatası, yönlendirme, health, bilinmeyen adres. Statik dosyalarda önbellek serbest.
- **Üretim çerezleri:** Oturum çerezi HttpOnly + Secure + SameSite=Lax; giriş öncesi CSRF çerezi
  HttpOnly + Secure + SameSite=Strict; HSTS 1 yıl. Üretimde izinli olmayan alan adı reddediliyor. API
  dokümanları (`/docs`, `/redoc`, `/openapi.json`) kapalı.
- **XSS:** Hatalı e-posta yansıtılırken kaçışlanıyor. Rol seçiminde HTML reddediliyor (mevcut test).
- **Sınırlar:** Günlük iş sınırı (silme yoksa) ve eşzamanlı iş sınırı (mevcut test) çalışıyor.

## Ayrıntılar

### G1 — Kopya üretiminde kaynak sınırı yok (Orta)
`app.py` `job_output` → `run_in_threadpool(runner.make_output, ...)`. `isolate_jobs=True` iken her istek
yeni bir süreç başlatıyor (`worker.output_isolated`; RLIMIT_AS 2 GB, süre sınırı var). `active_jobs`
ve günlük sayaç bu uç noktada kontrol edilmiyor. Oturum açmış bir kullanıcı aynı küçük `.docx`'i
paralel olarak N kez gönderip N süreç açtırabilir. 4 vCPU / 8 GB önerilen pilot sunucuda birkaç düzine
istek sunucuyu yanıt veremez hale getirir. Saldırgan için gereken: izinli alanda bir e-posta adresi.
`recheck` uç noktası eşzamanlı sınıra tabi ama günlük sınıra değil.

### G2 — Günlük sınırın silmeyle aşılması (Düşük–Orta)
`jobs_since` silinmemiş satırları sayıyor; "Raporu şimdi sil" satırı tamamen siliyor. Eşzamanlı sınır
(2) yine geçerli olduğu için etki sınırlı: günlük 20 yerine sürekli 2 paralel iş.

### G3 — Giriş isteği sınırı (Düşük–Orta)
`login_requests_since(email, ...)`. IP veya küresel sınır yok. Alan adı kısıtı kötüye kullanımı
üniversite adresleriyle sınırlıyor, ama pilotta tüm üniversiteye istenmeyen e-posta göndermek ve
gönderici itibarını düşürmek mümkün.

### G4 — Saklama süresi (Düşük)
`db.purge` başlangıçta ve 10 dakikada bir çalışıyor. `own_job` yaşa bakmıyor.

### G5 — altChunk (Düşük)
Sentetik belgeye `<w:altChunk r:id="rId99"/>` eklendi: rapor 0 bulgu döndürdü, uyarı yok.

## Bilgi notları (açık değil)
- Giriş öncesi CSRF "double-submit cookie" ile korunuyor. Aynı üst alandaki başka bir alt alan çerez
  yazabiliyorsa (cookie tossing) zayıflar. Synora'yı ayrı bir alt alanda yayınlarken `__Host-` önekli
  çerez adı düşünülebilir (`__Host-synora_pre`; Secure, Path=/, Domain yok).
- `uvicorn.run(..., proxy_headers=True)`: ters vekil arkasında `forwarded_allow_ips` yalnızca vekilin
  adresi olmalı. Ö7 IP sınırı eklenirse bu kritik hale gelir.
- Rapor JSON'u başlık metinlerini (başlık yolları) içeriyor. Bu mimari §10.3'e uygun, ama bilinçli bir
  tercih olarak KVKK metninde belirtilmeli (SORULAR #3).
