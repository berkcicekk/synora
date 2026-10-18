# Synora — Mimari

> Durum: **Taslak v0.2** (2026-10-12). `[KARAR?]` ile işaretli yerler henüz netleşmedi.

## 1. Amaç

Synora, `.docx` formatındaki tezleri bir enstitünün yazım kılavuzuna (YAML kural seti) göre **denetler** ve
isteğe bağlı olarak **biçimsel hataları düzeltir**. Tezin metnine hiçbir koşulda dokunmaz; yalnızca biçimi
(kenar boşluğu, yazı tipi, satır aralığı, başlık stilleri, sayfa numarası vb.) değiştirir.

Öğrenci tezini sade bir **web arayüzüne** yükler, raporu ekranda görür, isterse düzeltilmiş dosyayı indirir.
Görsel kimlik ve arayüz dili: Synora marka kiti (https://claude.ai/artifact/Bg7bwS9wQZqqiyaEWTHzMK).

**Pilot:** Zonguldak Bülent Ecevit Üniversitesi (ZBEÜ). İlk kural seti `rulesets/zbeu-tip.yaml`:
Tıp Fakültesi *Tıpta Uzmanlık Öğrencileri için Tez Yazım Kılavuzu* (2019). Kılavuzla madde madde eşleme,
kapsanmayan kurallar ve kılavuzdaki çelişkiler `rulesets/zbeu-tip.md`'de. Lisansüstü Eğitim Enstitüsü
(yüksek lisans/doktora) için ayrı kılavuz gerekir `[KARAR?]`.

**Diğer üniversiteler (2026-10-18):** 178 üniversitenin resmi kılavuzlarından otomatik çıkarılmış 246
kural seti `rulesets/` altında; kaynakları ve bulunamayanlar `rulesets/KAYNAKLAR.md`'de. Hiçbiri enstitü
tarafından doğrulanmadı. Varsayılan kılavuz `SYNORA_DEFAULT_RULESET` (öntanımlı `zbeu-tip`).

Kapsam dışı: yazım/dil denetimi, intihal, içerik önerisi, kaynakça içeriğinin doğruluğu.

## 2. Tasarım ilkeleri (değişmez)

1. **Metin dokunulmazdır.** Synora yalnızca biçim özelliklerini (`w:pPr`, `w:rPr`, `w:sectPr`, `styles.xml`,
   `numbering.xml`) değiştirir. Her yazma işleminden sonra `content_fingerprint` yeniden hesaplanır;
   girdiyle eşleşmezse çıktı **üretilmez** ve iş hata ile biter.
2. **Tek XML giriş kapısı.** Tüm XML `synora.xmlsafe.parse()` ile okunur (lxml; `resolve_entities=False`,
   `no_network=True`, `huge_tree=False`, DTD yok). `xml.etree`, `minidom` ve kendi XML'ini parse eden
   kütüphaneler (ör. `python-docx`) kullanılmaz.
3. **Güvensiz girdi varsayımı.** Her `.docx` saldırgan olabilir: zip bomb, path traversal, XXE, dev dosya,
   harici ilişki (`TargetMode="External"`), makro. Sınırlar A1'de uygulanır.
4. **Tez metni sızmaz.** Log, exception mesajı, metrik ve telemetride tez metni bulunmaz. Yalnızca
   `job_id`, `para_id`, `rule_id` ve hash'ler loglanır.
5. **Yapay zekâ metni görmez, yalnızca sınıflandırır.** Herhangi bir model (yerel ya da LLM) tez metnini,
   kelimelerini veya metin hash'ini almaz; yalnızca sunucuda çıkarılmış sayısal/kategorik özellikleri alır
   (bkz. §9). Çıktı Pydantic ile doğrulanmış `enum + float (güven)` olmak zorundadır; serbest metin reddedilir.
   Model asla belgeye yazılacak bir değer üretmez.
6. **Deterministik çekirdek.** Aynı belge ve aynı kural seti her zaman aynı bulguları üretir. LLM kararları
   iş başına önbelleğe alınır ve rapora "LLM kaynaklı" olarak işaretlenir.

## 3. Modüller

| Kod | Modül | Paket | Sorumluluk | Hassas* |
|-----|-------|-------|------------|---------|
| A1 | Güvenli giriş | `synora.ingest`, `synora.xmlsafe` | Zip doğrulama, boyut/oran sınırları, part beyaz listesi, güvenli XML parse | ✅ |
| A2 | Parser | `synora.parse` | OOXML → `DocModel` (paragraflar, run'lar, bölümler, stil kalıtımı çözülmüş) | ✅ |
| A3 | Kural seti | `synora.ruleset` | YAML → Pydantic `Ruleset`; şema doğrulama, sürümleme | |
| A4 | Rol sınıflandırma | `synora.classify` | Her paragrafa rol atar (başlık-1, gövde, şekil başlığı…): önce kural tabanlı, belirsizse LLM | |
| A5 | Düzeltici / yazıcı | `synora.fix`, `synora.write` | Bulgulardan XML yamaları üretir, uygular, fingerprint doğrular, `.docx` paketler | ✅ |
| A6 | Denetim motoru | `synora.check` | `DocModel` + roller + `Ruleset` → `Finding` listesi | |
| A7 | Rapor | `synora.report` | Bulguları JSON / terminal / HTML olarak sunar | |
| A8 | CLI | `synora.cli` | `synora check`, `synora fix` komutları (geliştirme ve enstitü içi toplu kullanım) | |
| A9 | Web API | `synora.web` | Dosya yükleme, iş oluşturma, rapor/çıktı indirme, oturum (FastAPI) | ✅ |
| A10 | İş yürütücü | `synora.worker` | Kuyruktaki işi izole süreçte çalıştırır (zaman/bellek sınırı), saklama süresi dolanları siler | ✅ |
| A11 | Arayüz | `web/` | Yükle → ilerleme → rapor → indir akışı; marka kitine uygun, mobil uyumlu, erişilebilir | |
| A12 | LaTeX şablonu | `synora.latex` | Kural setinden Overleaf'e yüklenebilir tez şablonu (.cls + örnek tez); derleme yok | |

\* Hassas modüllerde (A1, A2, A5, A9, A10) kod yazmadan önce plan sunulur ve onay beklenir (bkz. `CLAUDE.md`).

## 4. Akış

```
.docx
  │
  ▼
[A1] ingest ──► sınır aşımı / şüpheli part → RED (iş biter)
  │  (doğrulanmış part'lar, bellekte)
  ▼
[A2] parse ──► DocModel  ──► content_fingerprint(girdi)
  │
  ▼
[A4] classify ──► para_id → (Role, güven)
  │
  ▼
[A6] check (+ [A3] Ruleset) ──► list[Finding]
  │
  ├──► [A7] report            (synora check)
  │
  └──► [A5] fix ──► yamalı XML ──► content_fingerprint(çıktı) == girdi ?
                                       ├─ evet → yeni .docx + rapor   (synora fix)
                                       └─ hayır → çıktı yok, hata
```

## 5. Temel veri yapıları (taslak)

```python
class Role(StrEnum):
    TITLE = "title"; HEADING_1 = "heading_1"; HEADING_2 = "heading_2"; HEADING_3 = "heading_3"
    BODY = "body"; BLOCK_QUOTE = "block_quote"; LIST_ITEM = "list_item"
    FIGURE_CAPTION = "figure_caption"; TABLE_CAPTION = "table_caption"
    REFERENCE_ENTRY = "reference_entry"; TOC_ENTRY = "toc_entry"; FOOTNOTE = "footnote"
    FRONT_MATTER = "front_matter"; EMPTY = "empty"; UNKNOWN = "unknown"

class RoleDecision(BaseModel):          # LLM çıktısı tam olarak bu şemaya uymalı
    role: Role
    confidence: float = Field(ge=0.0, le=1.0)

class Finding(BaseModel):
    rule_id: str                        # ör. "body.line_spacing"
    para_id: str | None                 # w14:paraId ya da Synora'nın atadığı sıra kimliği
    section_index: int | None
    severity: Literal["error", "warning", "info"]
    expected: str                       # biçim değeri, ör. "1.5"  — asla tez metni değil
    actual: str
    fixable: bool
    source: Literal["rule", "llm"]
```

`DocModel` paragraf düzeyinde **çözülmüş** biçimi tutar (doğrudan biçim > paragraf stili > `basedOn` zinciri >
doc defaults). Denetim her zaman çözülmüş değer üzerinden yapılır.

## 6. content_fingerprint

Uygulama: `synora.fingerprint` + `synora.text` (metin tanımı tek yerde).

- Kapsam: gövde, dipnotlar, sonnotlar, üstbilgiler, altbilgiler; metin kutuları dahil.
- Her part'taki her `w:p` sırasıyla: görünen metin (`w:t`, `w:tab` → `	`, `w:br`/`w:cr` → `
`,
  `w:sym`, bölünmez/yumuşak tire) SHA-256 ile özetlenir. Run bölünmesi ve biçim özeti etkilemez.
- **Alan sonuçları dahil** (atıflar, kaynakça, TOC önbellek metni, sayfa numaraları). Synora alan
  sonuçlarına dokunmaz; Zotero/Mendeley atıfları da alan sonucu olduğu için hariç tutmak kaynakça
  değişikliklerini görünmez kılardı. Yalnızca **alan komutları** (`w:instrText`) hariç; A5 sayfa
  numarası biçimini (`PAGE \* roman`) değiştirebilir.
- Track changes: eklenen metin dahil, silinen metin hariç. `DocModel.has_tracked_changes` işaretlenir;
  raporda uyarı olarak gösterilecek (F2).
- Boş paragraf eklemek/silmek özeti değiştirir: A5 sayfa sonu için boş paragraf değil
  `pageBreakBefore` kullanmalı.

Hypothesis testleri: rastgele biçim + rastgele run bölünmesi → aynı özet; tek karakter ekleme/silme/
değiştirme → farklı özet.

## 7. Kural seti (YAML) örneği

```yaml
ruleset: ornek-enstitu
version: 1
page:
  size: A4
  margins_cm: { top: 3, bottom: 2.5, left: 3.5, right: 2.5 }
font:
  family: Times New Roman
  size_pt: 12
roles:
  body:
    line_spacing: 1.5
    alignment: justify
    first_line_indent_cm: 1.25
    space_after_pt: 6
  heading_1:
    size_pt: 14
    bold: true
    all_caps: true
    alignment: center
    page_break_before: true
  figure_caption:
    size_pt: 10
    position: below
  table_caption:
    position: above
page_numbering:
  front_matter: lower_roman
  body: arabic
  position: bottom_center
```

Her alan bir `rule_id`'ye karşılık gelir (`roles.body.line_spacing` → `body.line_spacing`). Bilinmeyen alan
şema hatasıdır (`extra="forbid"`).

## 8. A1 güvenlik sınırları (başlangıç değerleri)

| Sınır | Değer |
|-------|-------|
| Girdi dosya boyutu | ≤ 50 MB |
| Açılmış toplam boyut | ≤ 300 MB |
| Sıkıştırma oranı (part başına) | ≤ 100:1 |
| Part sayısı | ≤ 2000 |
| Part adı | `..`, mutlak yol, ters bölü yok |
| Content type | `.docx` ana tipi zorunlu; `.docm` / `vbaProject.bin` → RED |
| Harici ilişkiler | Takip edilmez, olduğu gibi korunur |
| `altChunk`, gömülü OLE | Dokunulmaz, uyarı bulgusu üretilir |

## 9. Metni görmeyen sınıflandırma (A4)

**Fikir:** Bir paragrafın "başlık mı, şekil başlığı mı, kaynakça girdisi mi" olduğunu anlamak için metnin
*anlamına* gerek yok; *biçimi* ve *şekli* yeterli. Synora metni sunucuda okur, ondan anonim sayılar ve
evet/hayır sinyalleri çıkarır, metnin kendisini atar. Modele yalnızca bu özellik vektörü gider.

### 9.1 Özellik vektörü (`ParaFeatures`, Pydantic, `extra="forbid"`)

| Grup | Örnek alanlar | Tip |
|------|---------------|-----|
| Biçim | punto, kalın, italik, büyük harf biçimi, hizalama, girinti (cm), önce/sonra boşluk, satır aralığı | float / bool / enum |
| Stil | stil adının **yerelde** eşlendiği kategori (`heading_1`, `caption`, `normal`, `custom`…) | enum |
| Konum | bölüm no, bölüm içi sıra (0–1), sayfa sonu öncesinde mi, tablo içinde mi, önceki/sonraki paragrafın rolü | int / float / bool / enum |
| Şekil sinyalleri | karakter sayısı, kelime sayısı, büyük harf oranı, nokta ile bitiyor mu | int / float / bool |
| Desen sinyalleri | numara deseni (`none`, `1.`, `1.1`, `1.1.1`, `roman`, `letter`), "Şekil/Tablo/Kaynakça/Ek" gibi anahtar kelimeyle başlıyor mu, köşeli parantezli atıf / "(Yazar, 2020)" deseni var mı | enum / bool |

Kural: Vektörde **hiçbir string alan yok**; yalnızca enum, sayı ve bool. Stil adları bile (kullanıcının
yazdığı serbest metin olabilir) sunucuda enum'a çevrilir. Bu, testle zorlanır: `ParaFeatures` şemasında `str`
tipli alan bulunursa test başarısız olur.

### 9.2 Sınıflandırıcı seçenekleri

| Seçenek | Nasıl | Artı | Eksi |
|---------|-------|------|------|
| **A. Kural tabanlı** | El yazımı eşikler (punto ≥14 + kalın + numara deseni `1.` → `heading_1`) | Deterministik, açıklanabilir, bedava | Alışılmadık belgelerde zayıf |
| **B. Yerel model** | Özellik vektörü üzerinde küçük bir model (ör. gradient boosting), sunucuda çalışır | Hiçbir veri dışarı çıkmaz, hızlı, ucuz | Etiketli eğitim verisi gerekir |
| **C. Bulut LLM** | Özellik vektörü + komşu bağlam JSON olarak gönderilir, `RoleDecision` döner | Az veriyle esnek | Ücretli, dış bağımlılık; metin görmeyince B'ye göre üstünlüğü sınırlı |

**Karar (pilot):** Önce A. Uygulandı: `synora.features` (özellik çıkarımı, metin burada kalır) →
`synora.classify` (yalnızca `ParaFeatures` görür). Belirsiz kalan paragraflar raporda "rolü belirsiz" diye işaretlenir. Kullanıcı arayüzde
rolü tek tıkla düzeltebilir; bu düzeltmeler (yalnızca özellik vektörü + etiket, metin yok, açık rıza ile)
B için eğitim verisi olur. C, B yeterli olmazsa `[KARAR?]` değerlendirilir.

### 9.3 Kurallar

- Çıktı: `RoleDecision`. Doğrulama başarısızsa `Role.UNKNOWN`, güven 0.0; asla tekrar deneme yok.
- Model katmanı tamamen kapatılabilir (`--no-model`); araç yalnızca A ile çalışır.
- Gönderilen her vektör için yalnızca `job_id`, `para_id` ve vektör hash'i loglanır.

## 10. Web (A9–A11)

### 10.1 Kullanıcı akışı

1. **Yükle:** Tek ekran. Sürükle-bırak alanı, enstitü/kural seti seçimi (pilotta yalnızca ZBEÜ), gizlilik notu:
   "Tezinizin metni değiştirilmez ve yapay zekâ tarafından okunmaz. Dosyanız işlem bitince silinir."
2. **İşleniyor:** İlerleme göstergesi (güvenlik kontrolü → okuma → denetim).
3. **Rapor:** Özet ("12 hata, 4 uyarı. 10'u otomatik düzeltilebilir."), bulgu listesi sayfa/bölüme göre
   gruplu, filtre (Hata / Uyarı / Düzeltilebilir). Rolü belirsiz paragraflar için "Bu bir … mi?" düzeltmesi.
4. **İndir:** Düzeltilmiş `.docx` ve PDF/HTML rapor. Düzeltilemeyen hatalar için Word'de nasıl düzeltileceği.

### 10.2 Teknik iskelet

Uygulandı: FastAPI + Jinja2 + az JavaScript (htmx yok), SQLite (WAL), iş yürütücü aynı süreçte iş
parçacıkları + her iş için ayrı alt süreç (Linux'ta bellek/CPU sınırı). Üretim kurulumu: `deploy/`
(systemd, nginx, ortam değişkenleri; tek süreç). Üretimde eksik ya da güvensiz ayarla uygulama başlamaz
(`Settings.problems`). Aşağıdaki ilk taslak tarihçe için duruyor:

- Backend: FastAPI (A9), iş kuyruğu (ör. RQ + Redis ya da Postgres tabanlı), ayrı worker süreci (A10).
- Frontend (A11): sunucu tarafı şablon + az JavaScript (htmx) ya da hafif bir SPA. Sade arayüz için htmx yeterli.
- Her iş ayrı geçici dizinde, worker süreci CPU/bellek/süre sınırıyla çalışır.

### 10.3 Veri ve KVKK

- Tez dosyası **diske hiç yazılmaz**: bellekte, ayrı süreçte işlenir. Düzeltilmiş/yorumlu kopya için öğrenci
  aynı dosyayı yeniden seçer; sunucu yalnızca ilk yüklemenin SHA-256 özetini tutar. Rapor (metin içermez,
  başlık yolları hariç) 24 saat sonra silinir; öğrenci hemen silebilir.
- Sunucu Türkiye'de barındırılır (KVKK yurt dışı aktarım). Model katmanı metin görmediği için tez metni hiçbir
  koşulda üçüncü tarafa gitmez.
- KVKK aydınlatma metni ve açık rıza (rol düzeltmelerinin eğitim verisi olarak kullanımı için ayrı onay).
- Giriş (`/giris`) ve kayıt (`/kayit`) ayrı sayfalar; ikisi de parolasız bağlantı gönderir. Kayıt,
  aydınlatma metni (`/aydinlatma`, **taslak**) onayı ister; onay (metin sürümü + zaman) yalnızca bağlantı
  açılıp e-posta doğrulanınca `users` tablosuna yazılır. Düz girişte kullanıcı satırı açılmaz.
- Kimlik doğrulama pilotta: üniversite e-postasına tek kullanımlık giriş bağlantısı `[KARAR?]`
  (ileride enstitünün SSO sistemi).
- Web'e özel ek sınırlar: kullanıcı başına eşzamanlı iş ≤ 2 (kopya üretimi dahil), günlük iş ≤ 20 (rapor
  silinse de düşmez), sunucu genelinde aynı anda en fazla `workers` kopya, kuyrukta en fazla 20 iş; formlar
  yalnızca URL kodlu ≤ 8 KB. CSRF koruması, yükleme yalnızca
  `.docx` uzantısı + içerik doğrulaması (A1).

## 10a. LaTeX şablonu (A12)

LaTeX ile yazan öğrenciler için Synora **denetim yapmaz**, kural setinden biçimi hazır ayarlanmış bir
şablon üretir: `synora-<kural seti>.cls`, örnek `tez.tex`, `kaynaklar.bib`, `BENIOKU.md` (kural → LaTeX
eşlemesi ve LaTeX'in kendiliğinden uygulayamadığı kurallar).

- Girdi yalnızca doğrulanmış `Ruleset`; kullanıcı dosyası alınmaz, sunucuda TeX derlenmez. Bu yüzden
  yeni bir saldırı yüzeyi ve tez metni söz konusu değildir.
- Kılavuz tek kaynakta: YAML değişince hem .docx denetimi hem şablon değişir.
- Çıktı deterministik (sabit zaman damgalı .zip). Yalnızca TeX Live'daki standart paketler kullanılır
  (testle zorlanır); pdfLaTeX (Times benzeri newtx) ve XeLaTeX (gerçek yazı tipi) desteklenir.
- Yazı tipi adı LaTeX'e yazılmadan önce beyaz listeyle süzülür; üretilen dosyalarda `\input`,
  `\write18` gibi dosya/kabuk komutları bulunmaz (testle zorlanır).
- Web: `GET /sablon/<id>/latex.zip` (girişsiz; şablon ilk istendiğinde üretilip saklanır). CLI:
  `synora latex -r <kural seti> -o <klasör|.zip>`.
- Kapsam dışı: `.tex` ya da PDF denetimi, sunucuda derleme.

## 11. Test stratejisi

- `tests/unit/` — modül başına birim testler.
- `tests/property/` — Hypothesis ile fingerprint değişmezliği.
- `tests/security/` — kötü niyetli `.docx` fixture'ları (zip bomb, XXE, traversal).
- `tests/fixtures/synthetic/` — test içinde üretilen belgeler.
- `tests/fixtures/real/` — yalnızca izinli belgeler; varsayılan olarak boş ve `.gitignore`'da.

## 12. Yol haritası

| Aşama | Çıktı |
|-------|-------|
| F0 | Proje iskeleti, `xmlsafe`, A1 (+ güvenlik testleri) |
| F1 | A2 parser + stil kalıtımı, fingerprint |
| F2 | A3 kural şeması + `rulesets/zbeu.yaml` + A6 sayfa/yazı tipi/gövde kuralları, `synora check` |
| F3 | A4 kural tabanlı rol sınıflandırma (`ParaFeatures`), başlık/şekil/tablo kuralları |
| F4 | A9–A11 web: yükle → rapor akışı (yalnızca denetim) |
| F5 | A5 düzeltici, web'den düzeltilmiş dosya indirme |
| **Pilot** | ZBEÜ'de sınırlı kullanıcıyla (ör. 20–30 öğrenci + enstitü personeli) deneme, geri bildirim |
| F6 | Rol düzeltmelerinden yerel model (seçenek B) |

## 13. Açık sorular

- ZBEÜ Lisansüstü Eğitim Enstitüsü'nün güncel tez yazım kılavuzu (PDF) ve şablon `.docx`'i. Fen ve sosyal
  bilimler için ayrı kurallar var mı?
- Pilot için enstitüde muhatap kim? Enstitünün format kontrolünü bugün kim, nasıl yapıyor?
- Fingerprint'te alan sonuçları ve track changes nasıl ele alınacak?
- Saklama süresi ve kimlik doğrulama yöntemi (§10.3).
- Barındırma: üniversite sunucusu mu, Türkiye'de bir bulut sağlayıcı mı?
