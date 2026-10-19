# Korumalı modüllerde yapmak isteyip yapmadığım değişiklikler

Korumalı: A1 (ingest, xmlsafe), A2 (parse), A5 (fix/annotate/write), A10 (worker), A9 backend (route'lar,
kimlik doğrulama, oturum, veritabanı). Her öneri: sorun → kanıt (varsa xfail test) → önerilen çözüm → risk.
Bağımlılık önerileri de burada.

## Ö1 — "Bu bulgu yanlış mı?" geri bildirimi (rakip analizi fikir 9)
> **Durum (2026-10-19): açık** (yeni özellik; canlıya çıkış için gerekmiyor).
- **Neden:** Pilotta yanlış bulgu oranını ölçmek için (UCSD pilotu bu ölçüyü tutuyor).
- **Öneri:** `POST /jobs/{id}/feedback` → gövde `{rule_id, para_id|null, verdict: "wrong"|"ok"}`.
  CSRF + sahiplik kontrolü olsun. Ayrı `feedback` tablosunda **metin olmadan** saklansın; iş silinince
  kayıt da silinsin, ama kural seti sürümüyle birlikte toplu sayım kalsın.
- **Risk:** Düşük. Sınırsız kayıt birikmemesi için `MAX_USER_ROLES` benzeri bir sınır gerekir.
- **Karar gerekli:** Geri bildirim verisinin saklama süresi (SORULAR).

## Ö2 — "Denetlenen maddeler" kontrol listesi (rakip analizi fikir 10)
> **Durum (2026-10-19): açık** (yeni özellik).
- **Neden:** Türk enstitülerinin kontrol formunun dijital karşılığı; danışmana gösterilebilir.
- **Öneri:** `report.to_json` raporuna `checked_rules: [rule_id...]` eklensin (bulgu çıkmayan, yani uygun
  kuralları da göstermek için). A7 korumalı değil ama rapor biçimi web ve testlerle bağlantılı; gece
  dokunmadım.
- **Risk:** Düşük. Rapor sürüm alanı artırılmalı.

## Ö3 — Bilinmeyen adres ve yanlış yöntem ham JSON döndürüyor
> **Durum (2026-10-19): çözüldü** — `78fe63c`.
- **Sorun:** `GET /boyle-bir-sayfa-yok` → `{"detail":"Not Found"}` (application/json). Kullanıcı marka
  dışında, açıklamasız bir ekran görüyor. Aynısı 405 için de geçerli.
- **Kanıt:** `tests/web/test_ui.py::test_unknown_url_shows_friendly_page` (xfail, strict).
- **Neden:** `app.py:560` `@app.exception_handler(HTTPException)` FastAPI'nin `HTTPException` sınıfına
  kayıtlı. Yönlendirici eşleşme bulamayınca Starlette'in temel `HTTPException` sınıfını fırlatıyor; bu
  sınıf FastAPI'ninkinin üst sınıfı olduğu için işleyiciye düşmüyor.
- **Öneri:** `from starlette.exceptions import HTTPException as StarletteHTTPException` ve işleyiciyi
  `@app.exception_handler(StarletteHTTPException)` olarak kaydetmek. Mevcut JSON dalları (POST /jobs vb.)
  aynen çalışır. Sonra xfail işaretini kaldırın.
- **Risk:** Çok düşük; tek satır.

## Ö4 — altChunk / gömülü OLE için uyarı bulgusu (mimari §8)
> **Durum (2026-10-19): açık** (A2 parser; xfail testi duruyor).
- **Sorun:** Mimari §8 "altChunk, gömülü OLE: dokunulmaz, uyarı bulgusu üretilir" diyor; A6 bunu
  üretmiyor. `altChunk` başka bir belgeyi (HTML/RTF/docx) gövdeye gömer; Synora onun içini denetlemez,
  ama kullanıcı bunu bilmez ve "temiz" rapor görebilir.
- **Kanıt:** `tests/security/test_ingest_more.py::test_alt_chunk_produces_warning` (xfail).
- **Öneri:** A2 parser `DocModel`'e `alt_chunks: int`, `ole_objects: int` sayaçları eklesin (yalnızca
  sayı, metin yok); A6 `document.alt_chunk` / `document.embedded_object` uyarısı üretsin; A7 mesajı:
  "Belgede başka bir dosyadan gömülü içerik var; bu kısım denetlenmedi." A2 korumalı → plan + onay.
- **Risk:** Düşük; yalnızca yeni uyarı.

## Ö5 — Günlük iş sınırı rapor silinerek aşılabiliyor
> **Durum (2026-10-19): çözüldü** — `d2ca3aa` (ayrı `job_starts` sayacı, e-posta özeti).
- **Sorun:** `db.jobs_since()` `jobs` tablosunu sayıyor; öğrenci "Raporu şimdi sil" ile kaydı silince
  sayaç düşüyor. 20/gün sınırı fiilen sınırsız.
- **Kanıt:** `tests/web/test_web_security.py::test_daily_job_limit_survives_deleting_reports` (xfail).
- **Öneri:** Ayrı `job_counts(email_hash, day, n)` tablosu ya da `jobs`'ta silme yerine raporu boşaltıp
  `deleted=1` işaretlemek (rapor JSON'u silinir, satır sayım için 24 saat kalır). E-posta yerine
  hash'i saklamak KVKK açısından daha iyi.
- **Risk:** Düşük. Silme sözü (rapor içeriği hemen silinir) korunur.

## Ö6 — Kopya üretimi (output) kaynak sınırı yok — ÖNCELİKLİ
> **Durum (2026-10-19): çözüldü** — `02e18fc` (kullanıcı ve sunucu geneli sınır, kuyruk sınırı).
- **Sorun:** `POST /jobs/{id}/output/{kind}` `active_jobs` ve günlük sınırı kontrol etmiyor; her istek
  `run_in_threadpool` + ayrı süreç (2 GB bellek sınırı) açıyor. Oturum açmış tek kullanıcı aynı iş için
  paralel istekle sunucuda N × 2 GB bellek ve CPU tüketebilir (DoS). `recheck` de günlük sınıra tabi değil.
- **Kanıt:** `tests/web/test_web_security.py::test_output_respects_concurrency_limit` (xfail).
- **Öneri:** (1) Kullanıcı başına bellek içi semafor/sayaç (ör. aynı anda 1 kopya), aşılırsa 429.
  (2) Sunucu genelinde `max_parallel_outputs` (ör. worker sayısı) semaforu. (3) `recheck` için günlük
  sayaca ekleme. Route mantığı (A9 backend) → plan + onay.
- **Risk:** Düşük; kullanıcı arayüzü 429 mesajını zaten gösteriyor.

## Ö7 — Giriş isteği sınırı yalnızca e-posta başına
> **Durum (2026-10-19): ilk katman nginx'te** (`deploy/nginx-synora.conf`, IP başına `limit_req`). Uygulama içi IP sınırı açık; xfail testi duruyor.
- **Sorun:** Saatte 5 sınırı e-posta başına. Tek istemci `@beun.edu.tr` altında istediği kadar farklı
  adrese bağlantı gönderebilir: e-posta bombardımanı, SMTP gönderici itibarının düşmesi, maliyet.
- **Kanıt:** `tests/web/test_web_security.py::test_login_requests_limited_per_client` (xfail).
- **Öneri:** IP başına (ör. saatte 20) ve genel (ör. dakikada 60) sınır; ters vekil arkasında gerçek IP
  için `proxy_headers` güvenli yapılandırılmalı (yalnızca güvenilen vekil). IP'nin kendisi değil hash'i
  ve kısa süreli tutulmalı (KVKK). Alternatif: ters vekilde (nginx `limit_req`) sınır.
- **Risk:** Orta (yanlış yapılandırmada aynı NAT arkasındaki öğrenciler etkilenir).

## Ö8 — Süresi dolan rapor, temizlik görevine kadar açılabiliyor
> **Durum (2026-10-19): çözüldü** — `a6cd11d` (okurken yaş denetimi, WAL boşaltma).
- **Sorun:** Temizlik 10 dakikada bir çalışıyor (`worker._janitor`). Arada `own_job` raporun yaşına
  bakmıyor; rapor 24 saat + 10 dakikaya kadar görülebilir. Gizlilik metni "24 saat sonra silinir".
- **Kanıt:** `tests/web/test_web_security.py::test_expired_report_is_not_served_before_purge` (xfail).
- **Öneri:** `own_job` içinde `job.created_at < now - retention` ise 404 (ve istersen o an sil).
- **Risk:** Çok düşük.

## Ö9 — Veritabanı okumalarında yarış: işler takılı kalıyor, ara sıra yanlış 404 — EN ÖNCELİKLİ
> **Durum (2026-10-19): çözüldü** — `d51a572`; test ara katmanı kaldırıldı.
- **Sorun:** `db.py` `Database.execute` kilidi yalnızca `execute()` sırasında tutuyor; çağıranlar
  `.fetchone()/.fetchall()`'u kilit dışında, tek paylaşılan `sqlite3` bağlantısında yapıyor. İş yürütücü
  iş parçacığı ile istek iş parçacığı aynı SQL'i (ör. `SELECT * FROM jobs WHERE id=?`) aynı anda
  çalıştırınca deyim önbelleğindeki aynı hazır deyim paylaşılıyor ve sonuçlar bozuluyor.
- **Belirtiler (gece testlerinde görüldü):**
  1. `worker.run_now` → `get_job()` yanlışlıkla `None` → işi "kullanıcı silmiş" sanıp `finish_job`
     çağırmıyor → iş sonsuza dek **"denetleniyor"** (öğrenci bekler durur; eşzamanlı sınır 2 olduğu için
     iki takılı iş yeni yüklemeyi de engeller → 429).
  2. `own_job` → `job.email` `None` → `TypeError` → 500.
  3. `sqlite3.InterfaceError`.
- **Kanıt:** `tests/unit/test_db_concurrency.py` (xfail, strict değil; 4×3000 okumada ~50 hata).
  Tam test takımı bu yüzden ~4 çalıştırmada 1 rastgele kırmızıya dönüyordu.
- **Öneri (tek fonksiyon):**
  ```python
  def execute(self, sql, params=()):
      with self._lock:
          cur = self._conn.execute(sql, params)
          return _Rows(cur.fetchall(), cur.rowcount)   # fetchone/fetchall/rowcount sağlayan liste
  ```
  ya da iş parçacığı başına bağlantı (`threading.local`) — WAL modunda okuyucular birbirini
  engellemez. Düzeltmeden sonra **`tests/web/conftest.py` içindeki `_serialize_db_reads` ara katmanını
  silin** (gece test takımını kararlı tutmak için eklendi; önerinin aynısı) ve
  `test_db_concurrency.py`'deki xfail'i kaldırın.
- **Risk:** Çok düşük; sonuçlar zaten küçük (tek iş / sayaç / son 10 iş).
- **Ek (Ö3):** `http_error` hata sayfasını `user` olmadan çiziyor; giriş yapmış kullanıcı üst menüde
  "Giriş yap" görüyor. `render(..., user=current_user(request))` eklenmeli.

## Ö10 — İki üniversitenin resmi şablonu customXml yüzünden tümden reddediliyor (A1)
> **Durum (2026-10-20): açık — kullanıcı kod değişikliğini şimdilik erteledi.**
- **Gözlem:** 40 resmi enstitü şablonuyla çapraz doğrulamada Bingöl FBE ve Fırat FBE şablonları
  `XML_MALFORMED` ile reddedildi. Neden: `customXml/item*.xml` içindeki `xmlns="Fırat
  Üniversitesi-FBE"` geçerli bir URI değil; Word hoş görüyor, lxml katı modda reddediyor.
  Synora bu part'ı hiç okumuyor. Bu şablonla yazılmış her öğrenci tezi de reddedilir.
- **Öneri:** Synora'nın okuduğu part'lar (hikâye part'ları, styles, numbering, theme, content
  types, rels) için katı `xmlsafe.parse` aynen kalsın; hiç okunmayan part'lar yalnızca bayt
  düzeyi süzgeçlerden geçsin (DOCTYPE yasağı, boyut/oran sınırları, makro yasağı değişmez) ve
  parse edilmeden olduğu gibi korunsun. Parse edilmeyen veri saldırı yüzeyi oluşturmaz.
- **Test:** `tests/security/` içine geçersiz xmlns'li customXml fixture'ı; kabul + fingerprint.

## Ö11 — Düzeltme rolleri değiştirince kapı kopyayı reddediyor (A5)
> **Durum (2026-10-20): açık — kullanıcı kod değişikliğini şimdilik erteledi.**
- **Gözlem:** 37 şablonun 14'ünde `WRITE_NEW_FINDINGS`: düzeltme (ör. başlığa `pageBreakBefore`)
  sayfa geometrisini değiştiriyor, sınıflandırıcı bazı paragrafları yeniden sınıflandırıyor
  (front_matter→body, cover→heading_1; `scratchpad` kanıtı: karabuk-lee-fen, ahievran-sabe,
  ebyu-sbe) ve bu paragrafların **zaten var olan** hataları ilk kez görünür oluyor. Kapı bunu
  "düzeltme hata yarattı" sayıp kopya vermiyor. Kapının kendisi doğru çalışıyor.
- **Öneri:** `fix_document` en fazla 3 tur: her turda yeniden denetle, yeni görünen
  düzeltilebilir bulguları da düzelt; kapı koşulları (metin aynılığı, yapı, açıklanamayan yeni
  bulgu yok) değişmeden son çıktıya uygulanır. 3 turda geçmezse bugünkü gibi kopya verilmez.
- **Yaygın yeni bulgular:** body.line_spacing ×37, body.space_after_pt ×32,
  body.first_line_indent_cm ×26 (14 şablon toplamı).
