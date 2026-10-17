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
