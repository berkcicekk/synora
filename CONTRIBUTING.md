# Katkı rehberi

Teşekkürler! Başlamadan önce `docs/architecture.md`'yi okuyun — özellikle "Tasarım ilkeleri"
(değişmez kurallar). Özet:

- **Tezin metni asla değişmez.** Her yazma işlemi `content_fingerprint` testinden geçmeli.
- XML yalnızca `synora.xmlsafe.parse()` ile okunur; `xml.etree`, `minidom`, `python-docx` yasak.
- Tez metni log'a, exception mesajına, modele gitmez.
- `tests/fixtures/real/` altına gerçek tez koymayın; yalnızca sentetik ya da izinli belge.

## Akış

1. Önce test yazın, sonra kod. Mevcut bir testi geçirmek için assertion değiştirmeyin.
2. Hassas modüllerde (A1 ingest, A2 parser, A5 yazıcı, A9 web, A10 worker) büyük değişiklik
   öncesi bir issue açıp yaklaşımı tartışın.
3. Göndermeden önce üçü de temiz olmalı:

```sh
uv run pytest -q
uv run ruff check . && uv run mypy src
uv run python tools/validate_rulesets.py
```

## Kural setleri

Yeni üniversite/enstitü kural seti eklemek en kolay katkıdır: `rulesets/` altındaki YAML
biçimini izleyin, kaynağını `rulesets/KAYNAKLAR.md`'ye ekleyin ve doğrulayıcıyı çalıştırın.
Resmi kılavuz PDF'siyle madde madde eşleşme notu (`rulesets/zbeu-tip.md` örneğindeki gibi)
büyük artı.

## Güvenlik

Açık bulduysanız issue açmayın; `SECURITY.md`'deki özel kanalı kullanın.

## Lisans

Katkılarınız projeyle aynı lisansla (AGPL-3.0-or-later) yayımlanır; PR göndererek bunu
kabul etmiş olursunuz.
