# Çapraz doğrulama: 40 resmi enstitü şablonu (2026-10-20)

Kaynak: üniversitelerin kendi sitelerindeki resmi Word tez şablonları (KAYNAKLAR.md'deki
kurumlar; şablonlar repoya konmadı, yalnızca geçici dizinde denetlendi). Her şablon kendi
kural setiyle `synora check`ten geçirildi; ardından stil körleştirmeli rol ölçümü
(`tools/role_eval.py`) çalıştırıldı. Bozma değerlendirmesi (`tools/mutation_eval.py`)
37 şablonda tamamlandı (2026-10-20, `--per-type 2 --seed 0`; sentetik tezde %100/%100).
Ham sayılar: `bozma-sonuclar.json`.

## Özet

- 39 şablon: 37 denetlendi, 2 reddedildi (Ö10: bingol-fbe, firat-fbe).
- Düzeltilmiş kopya: 23 şablonda verildi; 14 şablonda kapı reddi (Ö11).
- Metin parmak izi her üretilen kopyada değişmedi.
- Rol ölçümü (37 şablon, 1610 gümüş etiket): kesinlik %93,3 · kapsam %97,8.
  En sık karışanlar: içindekiler→başlık1 ×30, başlık2→başlık1 ×22, başlık3→başlık2 ×22.
- Bozma değerlendirmesi (37 şablon, 1840 deneme): yakalama %97,1; kopya verilen 23 şablonda
  düzeltme %100, kapı reddi olan 14 şablonda (Ö11) %0. Metin hiçbir denemede değişmedi.
- **Ö10+Ö11 düzeltmeleri sonrası (39 şablon, 1988 deneme): yakalama %97,0 · düzeltme %97,8 ·
  metin 0/1988.** Kapı reddi yalnızca firat-sabe'de kaldı (42).

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

## Kural seti mi, şablon mu? — kılavuz karşılaştırması (2026-10-20)

Altı şüpheli kural seti, kaynak kılavuzlarının yayındaki sürümleriyle madde madde
karşılaştırıldı (kılavuz PDF'leri indirildi; şablonların stil/bölüm tanımları Synora'nın
kendi parser'ıyla incelendi, metin okunmadı/yazdırılmadı):

- **hacettepe-ebe** (yönerge 2017): Yönerge *Arial 12 punto, 1,5 satır* diyor — kural seti
  kaynağına uygun. Şablon ise **APA 7** (05-2024, klasör 24.06.2026): 11 punto + 2,0 aralık.
  Hüküm: **kaynak sürüm çatışması** — enstitü fiilen APA 7 şablonu dağıtıyor; webde daha yeni
  yönerge bulunamadı. Enstitüye sorulmalı; o zamana dek bulgular şablon kullanıcıları için
  yanlış alarm.
- **sirnak-lee** (kılavuz 2026 v2 = şablonla aynı nesil): Kılavuz 1,5 aralık + 6 nk + 1 cm
  girinti + iki yana yaslı — kural setiyle birebir. Şablondaki *Body Text* stili de birebir
  uyumlu (line 360, firstLine 567 twip). Bulgular bu stili kullanmayan paragraflardan
  (Normal stili: tek aralık; yönerge metni/ön sayfalar). Hüküm: **kural seti doğru**;
  "kural seti sürümü?" şüphesi kalktı.
- **btu-lee** (kılavuz 2022): Kılavuz metni 1,5 aralık diyor (kural seti uygun) ama şablonda
  hiçbir stil satır aralığı tanımlamıyor (tek aralık) ve kılavuzun önsözü açıkça
  *"kılavuz ile tez şablonu arasında uyuşmazlık bulunması halinde tez şablonunu esas alınız"*
  diyor. Hüküm: **resmî çelişki, şablon kazanıyor** — body.line_spacing ×41 bulgu BTÜ şablonu
  kullanan öğrenci için yanlış alarm. Karar gerekli: kuralı şablona uydurmak mı, enstitüye
  sormak mı.
- **ytu-sbe** (kılavuz 2022): Kılavuz "sol 4 cm" diyor; şablon sol 2,5 cm + **cilt payı
  (gutter) 1,5 cm** = fiilen 4 cm. Kural seti de şablon da doğruydu; Synora sol kenar
  denetiminde cilt payını saymıyordu. Hüküm: **Synora hatasıydı, düzeltildi** (`3e0e732`,
  ölçüm tablosundaki 43 bulgu bu düzeltmeden önce; sonrası 27, kalan tek sol kenar bulgusu
  cilt payı olmayan kapak bölümünde).
- **marmara-fbe** (kılavuz 2012): Kılavuz her kenar 3 cm, 12 punto TNR, 1,5 aralık — kural
  seti kaynağına uygun. Şablon (10.03.2026) çok sayıda ve düzensiz sapıyor; webde daha yeni
  FBE kılavuzu bulunamadı (SBE/SABE'nin var, FBE'nin yok). Hüküm: **kaynak sürüm çatışması**;
  enstitü muhatabı gerekiyor.
- **ankara-fbe** (kılavuz 2013, yükleme 2024/01): Kılavuz 1,5 aralık diyor — kural seti
  uygun. Şablon (2026/01) stillerinde gövdeye 1,5 veren stil yok (Default tek aralık).
  Hüküm: **kaynak sürüm çatışması** (şablon kılavuzdan yeni).

Devam eden gözlemler:

- **cankaya-lee / karabuk-lee-fen:** page.margin.top ×15/×17 — bölüm başı sayfalarında üst
  kenarın bilerek büyütülmesi deseni; kılavuzlar "bölüm başlığı üst kenardan 4 cm aşağıda"
  kuralını bölüm kenarıyla uyguluyor. Kod tarafında açık soru.
- **deu-fbe:** enstitü 'kurallar şablondan üstündür' diyor; şablon kılavuzdan eski.

Çankaya/Karabük deseni ayrıca kod gözlemi: bölüm başlığı sayfalarında üst kenarı
bilerek büyüten şablonlarda `page.margin.top` bulgusu yanlış alarm olabilir (kılavuzlar
'bölüm başlığı üst kenardan 4 cm aşağıda' kuralını bölüm kenarıyla uyguluyor).

## Bozma değerlendirmesi (37 şablon, 1840 deneme)

Her şablonda, kural başına 2 paragraf/bölüm kılavuz dışına bozuldu (`--per-type 2 --seed 0`;
aynı komutla birebir tekrarlanır). Genel: **yakalama %97,1 · düzeltme %63,5 · metin değişimi 0/1840**.

> **Ö10+Ö11 sonrası (aynı gün, ikinci koşu):** 39 şablon (Bingöl ve Fırat artık kabul ediliyor),
> 1988 deneme: **yakalama %97,0 · düzeltme %97,8 · metin değişimi 0/1988.** Kapı reddi 653 → 42
> ve tamamı tek şablonda (firat-sabe: üç tur yetmiyor; düzeltme her turda yeni paragrafları
> yeniden sınıflandırıyor — elle bakılacak). Ham sayılar: `bozma-sonuclar-o11.json`.
> Aşağıdaki tablo Ö11 öncesi durumun kaydıdır.

- Düzeltme oranı şablon başına ya %100 ya %0: kopya verilen 23 şablonda bozmaların tamamı
  düzeltildi; %0 olan 14 şablon, denetim tablosundaki kapı reddi (Ö11) şablonlarının aynısı
  (653 deneme `WRITE_NEW_FINDINGS` kapısında durdu). Yani düzeltici çalıştığında eksiksiz;
  tek engel Ö11.
- Yakalanamayan denemeler rol değişimiyle örtüşüyor (49 denemede bozma paragrafın rolünü
  değiştirdi): en zayıflar body.alignment %68,8 (20 rol değ.), body.size_pt %81,0 (11),
  heading_1.bold %87,1 (9). Biçime bakan sınıflandırıcı, biçim bozulunca rolü de kaybedebiliyor;
  ölçüm yalnızca beklenen kuralın bulgusunu saydığı için paragraf başka kural altında bulgu
  verse de "kaçtı" görünür (doğrulanmadı).
- table_cell.font / table_cell.size_pt: 2/2 deneme kaçtı (tek şablonda) — elle bakılacak.

| Kural seti | Deneme | Yakalama | Düzeltme | Rol değ. | Kapı reddi |
|---|---|---|---|---|---|
| afsu-lee | 49 | %100 | %0 | 0 | 49 |
| ahievran-sabe | 70 | %97,1 | %0 | 2 | 68 |
| aksaray-fbe | 36 | %97,2 | %0 | 1 | 35 |
| aku-fbe | 58 | %96,6 | %100 | 2 | — |
| amasya-fbe | 42 | %100 | %0 | 0 | 42 |
| amasya-sabe | 49 | %98,0 | %0 | 1 | 48 |
| ankara-fbe | 37 | %89,2 | %100 | 4 | — |
| beykent-lee | 45 | %97,8 | %0 | 1 | 44 |
| bilgi-lpe | 44 | %100 | %100 | 0 | — |
| btu-lee | 71 | %98,6 | %100 | 1 | — |
| cankaya-lee | 25 | %92,0 | %100 | 2 | — |
| cu-fbe | 24 | %100 | %100 | 0 | — |
| deu-fbe | 51 | %100 | %100 | 0 | — |
| dicle-fbe | 67 | %95,5 | %100 | 3 | — |
| ebyu-fbe | 45 | %88,9 | %100 | 5 | — |
| ebyu-sbe | 55 | %96,4 | %0 | 2 | 53 |
| erciyes-fbe | 30 | %100 | %100 | 0 | — |
| erciyes-sbe | 48 | %97,9 | %100 | 1 | — |
| esogu-fbe | 27 | %85,2 | %0 | 4 | 23 |
| esogu-sabe | 10 | %100 | %0 | 0 | 10 |
| firat-sabe | 42 | %100 | %0 | 0 | 42 |
| giresun-sbe | 55 | %90,9 | %100 | 1 | — |
| hacettepe-ebe | 12 | %91,7 | %100 | 1 | — |
| itu-lee | 46 | %100 | %100 | 0 | — |
| karabuk-lee-fen | 44 | %100 | %0 | 0 | 44 |
| kastamonu-fbe | 61 | %96,7 | %100 | 2 | — |
| kayseri-lee | 61 | %96,7 | %100 | 2 | — |
| ktu-sbe | 61 | %100 | %100 | 0 | — |
| marmara-fbe | 26 | %84,6 | %100 | 4 | — |
| mu-fbe | 85 | %100 | %100 | 0 | — |
| odu-sbe | 73 | %95,9 | %0 | 3 | 70 |
| omu-lee | 63 | %100 | %0 | 0 | 63 |
| rteu-lee | 70 | %100 | %100 | 0 | — |
| sirnak-lee | 64 | %96,9 | %0 | 2 | 62 |
| yalova-lee | 67 | %100 | %100 | 0 | — |
| ytu-fbe | 64 | %98,4 | %100 | 1 | — |
| ytu-sbe | 63 | %93,7 | %100 | 4 | — |

"Düzeltme" yüzdesi yakalanan bozmalar içindir; "Kapı reddi" `WRITE_NEW_FINDINGS` ile
kopya verilmeyen deneme sayısıdır.

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
