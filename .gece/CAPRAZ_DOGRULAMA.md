# Çapraz doğrulama: 40 resmi enstitü şablonu (2026-10-20)

Kaynak: üniversitelerin kendi sitelerindeki resmi Word tez şablonları (KAYNAKLAR.md'deki
kurumlar; şablonlar repoya konmadı, yalnızca geçici dizinde denetlendi). Her şablon kendi
kural setiyle `synora check`ten geçirildi; ardından stil körleştirmeli rol ölçümü
(`tools/role_eval.py`) çalıştırıldı. Bozma değerlendirmesi (`tools/mutation_eval.py`)
37 şablonda başlatıldı; oranlar tamamlanınca buraya eklenecek (sentetik tezde %100/%100).

## Özet

- 39 şablon: 37 denetlendi, 2 reddedildi (Ö10: bingol-fbe, firat-fbe).
- Düzeltilmiş kopya: 23 şablonda verildi; 14 şablonda kapı reddi (Ö11).
- Metin parmak izi her üretilen kopyada değişmedi.
- Rol ölçümü (37 şablon, 1610 gümüş etiket): kesinlik %93,3 · kapsam %97,8.
  En sık karışanlar: içindekiler→başlık1 ×30, başlık2→başlık1 ×22, başlık3→başlık2 ×22.

## Şablon başına

| Kural seti | Bulgu | Belirsiz | Rol kesinlik (n) | Şüpheli başlık | Kopya | Kalan |
|---|---|---|---|---|---|---|
| afsu-lee | 111 | 12 | %100 (35) | 3 | kapı reddi | — |
| ahievran-sabe | 106 | 18 | %89 (88) | 8 | kapı reddi | — |
| aksaray-fbe | 59 | 31 | %100 (13) | 11 | kapı reddi | — |
| aku-fbe | 32 | 80 | %81 (64) | 2 | ✓ | 5 |
| amasya-fbe | 39 | 33 | %93 (28) | 10 | kapı reddi | — |
| amasya-sabe | 37 | 16 | %100 (72) | 4 | kapı reddi | — |
| ankara-fbe | 94 | 32 | %93 (45) | 6 | ✓ | 2 |
| beykent-lee | 81 | 3 | %71 (33) | 8 | kapı reddi | — |
| bilgi-lpe | 82 | 27 | %98 (51) | 2 | ✓ | 1 |
| bingol-fbe | — | — | — | — | RED (XML_MALFORMED) | — |
| btu-lee | 92 | 8 | %100 (49) | 2 | ✓ | 4 |
| cankaya-lee | 38 | 14 | %98 (51) | 8 | ✓ | 2 |
| cu-fbe | 25 | 6 | %100 (26) | 8 | ✓ | 2 |
| deu-fbe | 34 | 12 | %72 (36) | 1 | ✓ | 21 |
| dicle-fbe | 191 | 26 | %47 (18) | 23 | ✓ | 4 |
| ebyu-fbe | 168 | 15 | — (0) | 27 | ✓ | 2 |
| ebyu-sbe | 50 | 21 | %88 (54) | 8 | kapı reddi | — |
| erciyes-fbe | 9 | 22 | %91 (46) | 25 | ✓ | 2 |
| erciyes-sbe | 160 | 34 | %94 (34) | 12 | ✓ | 4 |
| esogu-fbe | 23 | 16 | — (0) | 14 | kapı reddi | — |
| esogu-sabe | 72 | 12 | %81 (24) | 21 | kapı reddi | — |
| firat-fbe | — | — | — | — | RED (XML_MALFORMED) | — |
| firat-sabe | 104 | 9 | %100 (65) | 2 | kapı reddi | — |
| giresun-sbe | 29 | 22 | %84 (64) | 0 | ✓ | 3 |
| hacettepe-ebe | 71 | 29 | %100 (32) | 21 | ✓ | 2 |
| itu-lee | 102 | 16 | %99 (114) | 3 | ✓ | 3 |
| karabuk-lee-fen | 90 | 24 | %97 (109) | 4 | kapı reddi | — |
| kastamonu-fbe | 68 | 14 | %100 (39) | 26 | ✓ | 4 |
| kayseri-lee | 232 | 30 | %97 (35) | 12 | ✓ | 11 |
| ktu-sbe | 45 | 9 | %100 (49) | 19 | ✓ | 3 |
| marmara-fbe | 339 | 70 | — (0) | 15 | ✓ | 3 |
| mu-fbe | 126 | 15 | %94 (37) | 8 | ✓ | 4 |
| odu-sbe | 81 | 9 | %97 (34) | 40 | kapı reddi | — |
| omu-lee | 85 | 25 | %100 (36) | 8 | kapı reddi | — |
| rteu-lee | 96 | 24 | %84 (94) | 0 | ✓ | 3 |
| sirnak-lee | 117 | 22 | %100 (56) | 4 | kapı reddi | — |
| yalova-lee | 20 | 7 | %100 (20) | 21 | ✓ | 1 |
| ytu-fbe | 139 | 34 | %97 (31) | 26 | ✓ | 2 |
| ytu-sbe | 43 | 18 | %100 (28) | 15 | ✓ | 2 |

“Şüpheli başlık”: başlık stili taşımadığı hâlde başlık sayılan paragraf sayısı; elle
bakılmadan doğru/yanlış bilinemez.

## Kural seti mi, şablon mu? (elle bakılacaklar)

Bir şablonun gövdesinin tamamı tek kuralda hatalıysa genellikle kural seti ya da kaynak
kılavuz sürümü şüphelidir:

- **hacettepe-ebe:** body.size_pt ve line_spacing şablonun tüm gövdesinde 'hatalı' (33/33)
- **sirnak-lee:** gövdenin tamamı girinti+satır aralığında hatalı (52/50) — kural seti sürümü?
- **btu-lee:** body.line_spacing ×41
- **ytu-sbe:** page.margin.left her bölümde (×17) — kenar değeri şüpheli
- **marmara-fbe:** 339 bulgu; şablon (03.2026) kural setinin kaynağından yeni
- **ankara-fbe:** şablon (2026/01) kılavuzdan (2024/01) yeni; line_spacing ×33
- **cankaya-lee:** page.margin.top ×15 — bölüm başı sayfalarında üst kenar bilerek farklı olabilir
- **karabuk-lee-fen:** page.margin.top ×17 — aynı desen
- **deu-fbe:** enstitü 'kurallar şablondan üstündür' diyor; şablon kılavuzdan eski

Çankaya/Karabük deseni ayrıca kod gözlemi: bölüm başlığı sayfalarında üst kenarı
bilerek büyüten şablonlarda `page.margin.top` bulgusu yanlış alarm olabilir (kılavuzlar
'bölüm başlığı üst kenardan 4 cm aşağıda' kuralını bölüm kenarıyla uyguluyor).

## Rol ölçümü (stil körleştirilmiş, 37 şablon)

```
## Hepsi · stil körleştirilmiş: 1610 etiketli paragraf · kesinlik  93.3% · kapsam  97.8% · başlık stili olmadan başlık sayılan 427
  rol              destek  kesinlik  duyarlılık  belirsiz
  figure_caption       47    100.0%      100.0%      0.0%
  heading_1           325     82.7%       93.8%      4.6%
  heading_2           176     84.7%       75.6%      8.0%
  heading_3           100     96.9%       63.0%      0.0%
  reference_entry      12     85.7%      100.0%      0.0%
  table_caption        33    100.0%      100.0%      0.0%
  toc_entry           917     99.9%       95.4%      0.8%
  en sık karışanlar: toc_entry→heading_1 ×30, heading_2→heading_1 ×22, heading_3→heading_2 ×22, heading_1→unknown ×15, heading_2→unknown ×14, heading_3→heading_1 ×12, toc_entry→unknown ×7, toc_entry→body ×4
```
