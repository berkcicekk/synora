# Gece modu kuralları (kullanıcının 2026-10-18 01:38 komutundan, aynen)

Her saatlik oturum bu dosyayı ve DURUM.md'yi okuyarak başlar.

## Fazlar (saat yaklaşık; yetişmezse sıradakine kaydır, hiçbir fazı aceleyle bozma)
- Faz 1 (00-01): Rakip analizi → .gece/RAKIP_ANALIZI.md. Fikir al, metin/tasarım/logo kopyalama.
- Faz 2 (01-03): Arayüz iyileştirme. Güven veren, sade, akademik görünüm; yükle → rapor → düzeltilmiş/yorumlu
  kopya akışı çok net; hata ve boş durum ekranları; mobil uyum; erişilebilirlik (WCAG AA kontrast, klavye,
  etiketler); tutarlı Türkçe metinler.
- Faz 3 (03-04): Güvenlik testleri. A1 (zip bomb, XXE, path traversal, makro, aşırı büyük dosya, bozuk docx) ve
  web (giriş bağlantısı yeniden kullanımı/süresi, CSRF, başkasının işine erişim, dosya türü sahteciliği,
  güvenlik başlıkları, hız sınırı). Açık → .gece/GUVENLIK_RAPORU.md.
- Faz 4 (04-05): Arayüz testi. Her sayfa ve akış uçtan uca, mobil görünüm; testi olabilecek her şeye test.
- Faz 5 (05-06): Son kontrol ve .gece/SABAH_RAPORU.md.

## Değişmez kurallar
- Her işe başlamadan `date +%H`. Saat 06–22 arasındaysa HİÇBİR değişiklik yapma; DURUM.md'ye
  "06:00 sonrası, kullanıcı kontrolü bekleniyor" yaz ve dur.
- .gece/DUR dosyası varsa hiçbir şey yapma ve dur.
- Yalnızca gece/arayuz-guvenlik dalı. push, merge, rebase, reset --hard yok. main'e dokunma.
- Proje klasörü dışında dosyaya dokunma. Hiçbir dosyayı silme (proje.txt dahil).
- Yeni bağımlılık ekleme, paket kurma → gerekirse ONERILER.md.
- Temel sözler: tezin metnine dokunulmaz, yapay zekâ metni görmez, dosya sunucuda saklanmaz.
  content_fingerprint kontrolüne ve ParaFeatures'ta str alan olmaması testine dokunma.
- KORUMALI MODÜLLER: A1 (ingest, xmlsafe), A2 (parse), A5 (fix/annotate/write), A10 (worker) ve A9 backend
  mantığı (route'lar, kimlik doğrulama, oturum, veritabanı). Kod DEĞİŞTİRME. A9'da yalnızca şablonlar, CSS,
  statik dosyalar ve kullanıcıya görünen metinler değişebilir. Açık/gereklilik → xfail test (gerekçeli) +
  ONERILER.md.
- rulesets/zbeu-tip.yaml'a dokunma.
- Açık kararlar (KVKK metni, barındırma, kimlik doğrulama yöntemi, saklama süresi, fiyatlandırma,
  Tıp/enstitü kapsamı) → SORULAR.md.
- Arayüze dış CDN, font, analytics, izleyici yok. Her şey yerel.
- İnternet yalnızca rakip araştırması ve dokümantasyon için. Hiçbir proje dosyası/tez hiçbir yere gönderilmez.
- Küçük adımlar: her anlamlı değişiklikten sonra tüm testler. Geçerse açıklayıcı commit. Geçmezse düzelt;
  olmazsa geri al (git checkout -- dosya / git revert) ve DURUM.md'ye yaz. Kırmızı testle commit yok.
- Bir işte 2 denemede ilerleme yoksa → SORULAR.md, sıradaki göreve geç.
- Her oturum sonunda DURUM.md güncellenir.

## Ek notlar (Claude)
- Proje GitHub adresi (kullanıcı verdi): https://github.com/berkcicekk/synora.git — bu gece push YOK; yerelde
  remote da tanımlı değil, eklenmedi.
- Kullanıcının andığı `frontend-design` skill'i bu oturumda yok; mevcut `artifact-design` ilkeleri ve proje
  marka kiti (CLAUDE.md) esas alınır.
