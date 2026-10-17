# Korumalı modüllerde yapmak isteyip yapmadığım değişiklikler

Korumalı: A1 (ingest, xmlsafe), A2 (parse), A5 (fix/annotate/write), A10 (worker), A9 backend (route'lar,
kimlik doğrulama, oturum, veritabanı). Her öneri: sorun → kanıt (varsa xfail test) → önerilen çözüm → risk.
Bağımlılık önerileri de burada.

## Ö1 — "Bu bulgu yanlış mı?" geri bildirimi (rakip analizi fikir 9)
- **Neden:** Pilotta yanlış bulgu oranını ölçmek için (UCSD pilotu bu ölçüyü tutuyor).
- **Öneri:** `POST /jobs/{id}/feedback` → gövde `{rule_id, para_id|null, verdict: "wrong"|"ok"}`.
  CSRF + sahiplik kontrolü olsun. Ayrı `feedback` tablosunda **metin olmadan** saklansın; iş silinince
  kayıt da silinsin, ama kural seti sürümüyle birlikte toplu sayım kalsın.
- **Risk:** Düşük. Sınırsız kayıt birikmemesi için `MAX_USER_ROLES` benzeri bir sınır gerekir.
- **Karar gerekli:** Geri bildirim verisinin saklama süresi (SORULAR).

## Ö2 — "Denetlenen maddeler" kontrol listesi (rakip analizi fikir 10)
- **Neden:** Türk enstitülerinin kontrol formunun dijital karşılığı; danışmana gösterilebilir.
- **Öneri:** `report.to_json` raporuna `checked_rules: [rule_id...]` eklensin (bulgu çıkmayan, yani uygun
  kuralları da göstermek için). A7 korumalı değil ama rapor biçimi web ve testlerle bağlantılı; gece
  dokunmadım.
- **Risk:** Düşük. Rapor sürüm alanı artırılmalı.

## Ö3 — Bilinmeyen adres ve yanlış yöntem ham JSON döndürüyor
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
