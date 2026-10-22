# Payper

Payper, `.docx` tezleri enstitünün yazım kılavuzuna göre **denetler** ve biçimsel hataları
**metne dokunmadan** düzeltir. Öğrenci tezini web arayüzüne yükler, raporu ekranda görür,
isterse düzeltmeleri Word'de izlenen değişiklik olarak taşıyan kopyayı indirir.

Demo: https://demo.payper.live · Pilot: Zonguldak Bülent Ecevit Üniversitesi (Tıp Fakültesi)

> Kod adları tarihsel nedenle `synora` (paket, CLI, `SYNORA_*` ortam değişkenleri);
> ürün adı Payper'dır. Ayrıntı: `docs/architecture.md`.

## Değişmez ilkeler

- **Metin dokunulmazdır.** Her yazma işlemi `content_fingerprint` doğrulamasından geçer;
  metin birebir aynı değilse çıktı üretilmez.
- **Yapay zekâ metni görmez.** Paragraf rolleri yalnızca sayısal/kategorik özelliklerden
  (`ParaFeatures`, str alanı yok) belirlenir.
- **Tez dosyası diske yazılmaz**, rapor 24 saat sonra silinir; log'da tez metni bulunmaz.
- Her `.docx` güvensiz kabul edilir (zip bomb, XXE, makro sınırları `synora.ingest`'te).

## Kurulum ve komutlar

[uv](https://docs.astral.sh/uv/) ile:

```sh
uv sync
uv run pytest -q                 # testler
uv run ruff check . && uv run mypy src

uv run synora check tez.docx -r rulesets/zbeu-tip.yaml     # denetim raporu
uv run synora fix   tez.docx -r rulesets/zbeu-tip.yaml -o duzeltilmis.docx
uv run synora word  -r rulesets/zbeu-tip.yaml -o sablon.docx   # stilleri hazır Word şablonu
uv run synora latex -r rulesets/zbeu-tip.yaml -o sablon.zip    # Overleaf şablonu
uv run synora serve --dev        # web arayüzü (geliştirme)
```

## Kural setleri

`rulesets/` altında 178 üniversiteden 249 kural seti bulunur (kaynaklar:
`rulesets/KAYNAKLAR.md`). Resmî kılavuzlardan otomatik çıkarılmıştır ve **enstitüler
tarafından doğrulanmamıştır**; çelişki saptananlar `uyari:` alanıyla işaretlidir.
Üretilen Word şablonunun her kural setinden sıfır bulguyla geçmesi testle zorlanır.

## Üretim

`deploy/README.md` (systemd + nginx) ya da kökteki `Dockerfile` + `compose.yaml`.
Üretimde eksik ya da güvensiz ayarla uygulama başlamaz (`SYNORA_*` değişkenleri için
`deploy/synora.env.example`).

## Katkı

Rehber: [CONTRIBUTING.md](CONTRIBUTING.md) · Mimari ve değişmez kurallar: `docs/architecture.md`.
Önce test, sonra kod; güvenlik, parser, yazıcı ve web/worker modüllerinde (A1, A2, A5, A9, A10)
değişiklik planla başlar. Güvenlik açıkları için: [SECURITY.md](SECURITY.md).

## Lisans

[GNU AGPL-3.0-or-later](LICENSE). Kodu kullanabilir, değiştirebilir ve kendi sunucunuzda
barındırabilirsiniz; Payper'ı bir ağ hizmeti olarak sunuyorsanız yaptığınız değişikliklerin
kaynağını da aynı lisansla açmanız gerekir.
