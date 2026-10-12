# ZBEÜ Tıp Fakültesi kural seti: kılavuz eşlemesi

Kaynak: *Tıpta Uzmanlık Öğrencileri için Tez Yazım Kılavuzu*, ZBEÜ Tıp Fakültesi, Zonguldak 2019
(https://cdn3.beun.edu.tr/tip//zbeu-tipta-uzmanlik-ogrencileri-icin-tez-yazim-kilavuzu.pdf).
Kural seti: `rulesets/zbeu-tip.yaml`.

> Bu kılavuz **Tıp Fakültesi tıpta uzmanlık tezleri** içindir; Lisansüstü Eğitim Enstitüsü'nün
> yüksek lisans/doktora tezleri için ayrı bir kılavuz gerekir.

## Fakülteye sorulacak çelişkiler

| # | Konu | Kılavuz metni | Kılavuz şekli | Kural setinde |
|---|------|---------------|----------------|---------------|
| Ç1 | Sol kenar boşluğu | 3.4: "sol kenarında 4 cm" | Şekil 1: "Soldan 3 cm" | 4 cm (metin) |
| Ç2 | Paragraf girintisi | 3.6: "1 cm içerden" | Şekil 1: "Paragraf başı 1.5 cm içeriden" | 1 cm (metin) |
| Ç3 | 1. düzey başlık puntosu | 3.3: "Birinci derece başlıklar 14 punto" | 3.8: "Her dereceden bölüm başlıkları … metinle aynı puntoda" | 14 pt (3.3 ve Şekil 1) |
| Ç4 | Önsöz sayfa numarası | 3.5: ön sayfalar "ii"den başlar | 5.3: hem "iii olarak belirtilir" hem "ii olarak numaralandırılır" | Yalnızca biçim (Roma rakamı) denetlenir |

## Denetlenen kurallar

| Kılavuz | Kural | `rule_id` |
|---------|-------|-----------|
| 3.1 | A4 kağıt | `page.size`, `page.orientation` |
| 3.3 | Times New Roman | `*.font` |
| 3.3 | Ana metin 12 pt, dipnot 10 pt | `body.size_pt`, `footnote.size_pt` |
| 3.3 | 1. derece başlık 14 pt, 2. ve 3. derece 12 pt | `heading_1/2/3.size_pt` |
| 3.4 | Kenar boşlukları: sol 4, üst 3, alt 3, sağ 2,5 cm | `page.margin.*` |
| 3.4 | İki yana yaslı | `body.alignment` |
| 3.5 | Ön sayfalar küçük Roma, Giriş'ten itibaren Arap rakamı | `page_numbering.formats` |
| 3.6 | Ana metin, şekil/tablo yazıları, alıntılar, kaynaklar 1,5 satır | `body/figure_caption/table_caption/block_quote/reference_entry.line_spacing` |
| 3.6, 3.13 | Dipnotlar tek satır aralığı | `footnote.line_spacing` |
| 3.6 | Paragraf 1 cm içeriden | `body.first_line_indent_cm` |
| 3.6 | 1. derece başlıklar sayfa başından | `heading_1.page_break_before` |
| 3.8 | 1. derece: tamamı büyük harf, ortalı, koyu | `heading_1.all_caps/alignment/bold` |
| 3.8 | 2. ve 3. derece: sola yaslı, koyu | `heading_2/3.alignment/bold` |
| 3.5 | Sayfa numarası altta ve sağda; yanında parantez yok | `page_numbering.position`, `page_numbering.decoration` |
| 3.8 | 2. derece başlık Her Sözcüğün İlk Harfi Büyük, 3. derece yalnızca ilk sözcük (uyarı) | `heading_2/3.case` |
| 3.15 | Tablo başlığı tablonun üstünde, şekil yazısı şeklin altında | `table_caption.position`, `figure_caption.position` |
| 5.3 | Önsöz tek satır aralıklı olabilir: ön sayfa metninde satır aralığı denetlenmez | `front_matter.size_pt` |
| — | Teslimde değişiklik izleme kalmamalı | `document.tracked_changes` |

## Henüz denetlenmeyen kurallar

| Kılavuz | Kural | Neden |
|---------|-------|-------|
| 3.6 | Başlıklar, tablo/şekil ile metin arasında "3 tane 1.5'luk satır aralığı (yani bir satır)" boşluk | İfade belirsiz (3 satır mı, 1 satır mı?) ve çoğu öğrenci bunu boş paragrafla yapar; netleşince `space_before_pt`/`space_after_pt` olarak eklenebilir |
| 3.8 | Üçüncü dereceden ileri başlık kullanılmamalı | 4. düzey başlık tespiti eklenebilir |
| 3.13 | Dipnot ayırıcı çizgisi sayfanın ortasına kadar | Word varsayılanı; denetlenmiyor |
| 3.15 | Çok satırlı açıklamalarda asılı girinti | Planlı |
| 3.10, 4.7 | Vancouver, metindeki geçiş sırasıyla numaralı kaynaklar | İçerik/sıra denetimi; kapsam dışı (ileride yerel olarak) |
| 3.7 | Yabancı sözcükler ve Latince türler italik | Metin anlamı gerektirir; kapsam dışı |
| 5.x | Kapak ve özet sayfasının iç düzeni (anahtar kelimeler, başlık sırası) | Kapak/özet düzeni kuralları henüz yok; ön sayfa metni yalnızca punto/yazı tipi açısından denetlenir |
| 6.x | Dizinlerin tablo içinde verilmesi | Kapsam dışı |
