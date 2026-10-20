# CLAUDE.md — Payper (kod adı: synora)

## Proje
Payper (eski adı Synora; paket/env/CLI adları `synora`/`SYNORA_*` olarak kalır): .docx tezleri
enstitü kural setine göre denetleyen/düzelten web aracı. Pilot: ZBEÜ. Demo: https://demo.payper.live
Mimari: @docs/architecture.md (değişmez kurallar oradaki "Tasarım ilkeleri"nde)
Arayüz: Synora marka kiti (https://claude.ai/artifact/Bg7bwS9wQZqqiyaEWTHzMK) dışına çıkma.

## Değişmez kurallar (ihlal = PR reddedilir)
- Belgenin metin içeriği ASLA değişmez. Her yazma işlemi content_fingerprint testinden geçmeli.
- XML yalnızca `synora.xmlsafe.parse()` ile okunur (XXE kapalı). `xml.etree`, `minidom` yasak.
- Tez metni loglanmaz, exception mesajına konmaz. Log'da yalnızca job_id, para_id, hash.
- Hiçbir model (LLM dahil) tez metnini görmez; yalnızca `ParaFeatures` (enum/sayı/bool, str alan yok) alır.
- Model çıktısı yalnızca Pydantic ile doğrulanmış enum + float. Serbest metin kabul edilmez.
- Tez dosyası diske/veritabanına yazılmaz (yalnızca SHA-256 özeti). Rapor 24 saat sonra silinir.
- A5 çıktısı `write.verify_output` kapılarından geçmeden kullanıcıya verilmez; kapıları gevşetme.
- tests/fixtures/real/ altına gerçek tez KOYMA; yalnızca sentetik veya izinli belge.

## Komutlar
- Test: `uv run pytest -q`
- Lint/tip: `uv run ruff check . && uv run mypy src`
- CLI: `uv run synora check <docx> --ruleset rulesets/example.yaml [--format json]`
- Düzelt: `uv run synora fix <docx> -r rulesets/example.yaml -o duzeltilmis.docx`
- Word şablonu: `uv run synora word -r rulesets/zbeu-tip.yaml -o sablon.docx`
- Web (geliştirme): `uv run synora serve --dev` → giriş bağlantısı konsola yazılır
- Demo: `uv run python scripts/demo.py`
- LaTeX şablonu: `uv run synora latex -r rulesets/zbeu-tip.yaml -o sablon.zip`
- Kural setlerini doğrula: `uv run python tools/validate_rulesets.py`; kaynak dizinini yenile: `uv run python tools/rulesets_index.py`
- `uv` PATH'te değilse: `python -m uv run ...`

## Çalışma biçimi
- Önce test yaz, sonra kod. Mevcut bir testi geçirmek için assertion'ı değiştirme; neden başarısız olduğunu açıkla.
- Güvenlik, parser, yazma ve web/worker (A1, A2, A5, A9, A10) kodunda önce plan sun, onay bekle.
