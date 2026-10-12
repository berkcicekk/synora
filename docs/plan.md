# Synora — Uygulama Planı

> Mimari: `docs/architecture.md`. Bu dosya fazları, her fazın işlerini ve "bitti" tanımını tutar.
> Durum işaretleri: ⬜ başlamadı · 🔄 sürüyor · ✅ bitti · ⛔ bekliyor (dış bağımlılık)

## Genel bakış

| Faz | Konu | Modüller | Hassas | Bağımlılık | Durum |
|-----|------|----------|--------|------------|-------|
| F0 | Temel + güvenli giriş | A1, xmlsafe | ✅ | — | ✅ |
| F1 | Belge modeli + fingerprint | A2 | ✅ | F0 | ✅ |
| F2 | Kural seti + denetim, `synora check` | A3, A6, A7 (JSON/terminal), A8 | | F1, ZBEÜ kılavuzu (⛔ yalnızca `zbeu.yaml` için) | ✅ (`zbeu-tip.yaml` ✅, enstitü ⛔) |
| F3 | Metni görmeyen rol sınıflandırma | A4 | | F2 | ✅ |
| F4 | Web: yükle → rapor | A9, A10, A11, A7 (HTML) | ✅ | F3, marka kiti | ✅ |
| F5 | Düzeltici + indirme | A5 | ✅ | F4 | ✅ |
| P | ZBEÜ pilotu | yayın, KVKK, destek | | F5 + dış işler | ⬜ |
| F6 | Yerel model (seçenek B) | A4 | | pilot verisi | ⬜ |

Her faz için ortak "bitti" tanımı:
- `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src` (strict) temiz.
- Yeni davranışın testi önce yazıldı (TDD); hiçbir mevcut assertion gevşetilmedi.
- Log ve exception'larda tez metni yok (log testi).
- `docs/architecture.md` ile çelişen bir karar alındıysa önce belge güncellendi.
- Faz sonunda tek bir git commit / PR, kısa demo komutuyla.

---

## F0 — Temel + güvenli giriş

**Hedef:** Saldırgan bir `.docx` bile sistemi çökertemez ya da dışarı veri sızdıramaz. Geçerli bir `.docx` ise
doğrulanmış part'lar halinde belleğe alınır.

İşler:
1. Araç zinciri: `uv` kurulumu, `git init`, `.gitignore`, `pyproject.toml` (Python 3.12; lxml, pydantic, typer;
   geliştirme: pytest, hypothesis, ruff, mypy, lxml-stubs).
2. Klasör yapısı: `src/synora/`, `tests/{unit,security,property}/`, `tests/fixtures/{synthetic,real}/`, `rulesets/`.
3. `synora.errors`: metin içermeyen hata kodları (`IngestError(code=...)`).
4. `synora.log`: yalnızca izinli alanları (`job_id`, `para_id`, `rule_id`, `hash`, `code`) yazan logger.
5. `synora.xmlsafe.parse()`: tek XML giriş kapısı.
6. `synora.ingest.open_docx()`: zip ve paket doğrulama → `DocxPackage`.
7. Test yardımcısı: sentetik `.docx` üreten builder (sonraki fazlarda da kullanılır).
8. Güvenlik test seti: zip bomb, path traversal, XXE, billion laughs, DOCTYPE, `.docm`/makro, şifreli zip,
   boyutu yalan söyleyen zip başlığı, eksik `[Content_Types].xml`, çok fazla part.
9. Mimari kural testleri: `xml.etree` / `minidom` import'u kaynakta varsa test başarısız olur.

Bitti: geçerli sentetik belge açılıyor; 10+ kötü niyetli fixture'ın her biri doğru hata koduyla reddediliyor.

## F1 — Belge modeli + fingerprint

**Hedef:** `.docx` → `DocModel`: her paragrafın stil kalıtımı çözülmüş biçimi, bölümler ve sayfa ayarları.
Metnin değişmediğini kanıtlayan `content_fingerprint`.

İşler: `document.xml`, `styles.xml`, `numbering.xml`, `footnotes/endnotes` okuma; stil kalıtım zinciri
(doğrudan > paragraf stili > basedOn > docDefaults); `sectPr` → sayfa boyutu/kenar boşlukları; tablolar ve
içindeki paragraflar; `para_id` atama; fingerprint (§6) + Hypothesis testleri.

Bitti: Word, LibreOffice ve Google Docs'tan çıkmış birer sentetik belgede beklenen çözülmüş değerler;
fingerprint, biçim değişikliğinde sabit, tek karakter metin değişikliğinde farklı.

## F2 — Kural seti + denetim

**Hedef:** `uv run synora check tez.docx --ruleset rulesets/zbeu.yaml` → bulgu listesi.

İşler: Pydantic `Ruleset` şeması (`extra="forbid"`); kural motoru (sayfa, yazı tipi, gövde paragrafı,
sayfa numarası); `Finding`; terminal ve JSON rapor; CLI. `rulesets/zbeu.yaml` ZBEÜ kılavuzundan çıkarılır;
kılavuzdaki her madde → `rule_id` eşleme tablosu (`rulesets/zbeu.md`) ile, kapsanmayan maddeler açıkça listelenir.

Bitti: ZBEÜ şablonundan üretilmiş "temiz" belgede 0 hata; kasıtlı bozulmuş kopyada beklenen bulgular.
⛔ Kılavuz gelene kadar şema ve motor `rulesets/example.yaml` ile geliştirilir.

Not (F2'de yapıldı): F3 gelene kadar roller stil adı + yapı + yerel desenlerle atanır
(`synora.roles`). Stilsiz, elle kalınlaştırılmış kısa satırlar "rolü belirsiz" sayılır ve denetlenmez.

## F3 — Metni görmeyen rol sınıflandırma

**Hedef:** Her paragrafa rol (başlık-1, gövde, şekil başlığı…) ve güven; başlık/şekil/tablo/kaynakça kuralları.

İşler: `ParaFeatures` (str alan yasak; testle zorlanır); özellik çıkarıcı; kural tabanlı sınıflandırıcı;
belirsiz rollerin rapora "rolü belirsiz" olarak düşmesi; rol bazlı kurallar.

Bitti: etiketli sentetik test setinde rol doğruluğu ölçülüyor ve raporlanıyor (hedef ≥ %90, belirsizler hariç).

Sonuç (2026-10-12): sentetik derlemde (12 tohum, 754 paragraf) kesinlik %100, kapsam %100.
Derlemi sınıflandırıcıyı yazan taraf ürettiği için bu bir **üst sınırdır**; gerçek tezlerdeki
doğruluk pilotta ve izinli örneklerle ölçülmeli. Derlem dışı testler kapak sayfası kuralındaki
bir zayıflığı yakaladı ve düzeltildi.

## F4 — Web: yükle → rapor

**Hedef:** Öğrenci tarayıcıdan tezini yükler, raporu görür. Henüz düzeltme yok.

İşler: FastAPI (A9); iş kuyruğu + izole worker, süre/bellek sınırı, saklama süresi dolunca silme (A10);
arayüz (A11): marka kitine uygun yükleme, ilerleme, rapor ekranları, mobil ve erişilebilirlik (WCAG AA);
e-posta ile tek kullanımlık giriş; hız sınırları; CSRF.

Bitti: uçtan uca test (yükle → rapor); dosyanın süre sonunda gerçekten silindiği test; Lighthouse erişilebilirlik ≥ 95.

Yapılan (2026-10-12): FastAPI + sunucu taraflı şablonlar + bağımlılıksız JS; e-posta ile tek kullanımlık
giriş (GET bağlantıyı tüketmez); tez yalnızca bellekte, ayrı süreçte ve süre sınırıyla işlenir, diske
yazılmaz; rapor 24 saat sonra silinir, kullanıcı hemen silebilir; CSRF, sıkı CSP (inline yok), güvenlik
başlıkları, eşzamanlı/günlük iş sınırları; yazı tipleri yerelde (Google'a istek yok); bulgu yeri başlık
yoluyla gösterilir. Açık: Lighthouse ölçümü yapılmadı; SMTP gerçek sunucuyla denenmedi; logo SVG yok.

## F5 — Düzeltici

**Hedef:** Otomatik düzeltilebilir bulgular için düzeltilmiş `.docx`, metin aynen korunarak.

İşler: bulgu → XML yaması; yamaları uygulama; fingerprint doğrulaması (eşleşmezse çıktı yok); yeniden paketleme;
düzeltilmiş dosyanın Word ve LibreOffice'te açıldığının testi; web'den indirme; düzeltilemeyenler için
"Word'de nasıl düzeltilir" yönergeleri.

Bitti: düzeltilmiş belge yeniden denetlendiğinde düzeltilebilir hata sayısı 0; fingerprint her testte eşit.

Yapılan (2026-10-12), kullanıcı kararlarıyla:
- Düzeltmeler **izlenen biçim değişikliği** (pPrChange/rPrChange/sectPrChange, yazar "Synora").
- Sunucu dosya tutmaz: düzeltilmiş/yorumlu kopya için öğrenci **aynı dosyayı yeniden seçer**;
  yalnızca SHA-256 özeti karşılaştırılır, çıktı doğrudan indirilir.
- **Yorumlu kopya**: her bulgu ilgili paragrafa Word yorumu olarak eklenir.
- Beş doğrulama kapısı (metin, yeniden okuma, yeniden denetim, dokunulmayan part'lar, yapı).
- Bilerek otomatik düzeltilmeyenler: gövdedeki italik/kalın kaldırma, rolü belirsiz paragraflar,
  kapak, öğrencinin kendi değişiklik kaydı olan paragraflar, bölüm sayısı eşleşmeyen sayfa numaraları.
- LibreOffice ile açılabilirlik otomatik test ediliyor. **Açık:** Word'de elle açılış testi.

## P — ZBEÜ pilotu

İşler: Türkiye'de barındırma; KVKK aydınlatma metni ve rıza; enstitüyle kapsam ve takvim; 20–30 öğrenci +
enstitü personeli; kullanım kılavuzu; geri bildirim formu; haftalık hata/istek takibi.

Başarı ölçütleri `[KARAR?]`: enstitü format iadelerinde azalma, kullanıcı memnuniyeti, yanlış pozitif oranı.

## F6 — Yerel model

Pilotta toplanan (rızalı, yalnızca özellik + etiket) rol düzeltmeleriyle küçük model; kural tabanlıyla karşılaştırma.

---

## Kod dışı işler (paralel)

| İş | Sorumlu | Gerektiği faz |
|----|---------|---------------|
| ZBEÜ Tıp Fakültesi kılavuzu (2019) → `rulesets/zbeu-tip.yaml` ✅; 4 çelişki fakülteye sorulmalı (`rulesets/zbeu-tip.md`) | Kullanıcı | P |
| ZBEÜ Lisansüstü Eğitim Enstitüsü kılavuzu (yüksek lisans/doktora için) | Kullanıcı | P (kapsam kararı) |
| Enstitüde pilot muhatabı | Kullanıcı | P (konuşmaya erken başlanmalı) |
| Logo SVG + koyu zemin sürümü | Tasarımcı | F4 |
| Barındırma kararı (üniversite sunucusu / TR bulut) | Kullanıcı + enstitü | F4 |
| KVKK aydınlatma metni (hukuk görüşü) | Kullanıcı | P |
| İzinli gerçek tez örnekleri (test için) | Enstitü | F2–F5 |
