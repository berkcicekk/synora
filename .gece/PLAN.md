# Gece planı — gece/arayuz-guvenlik (2026-10-18)

Kurallar: `.gece/KURALLAR.md`. Durum: `.gece/DURUM.md`. Her görev küçük ve testle doğrulanır; her anlamlı
adımdan sonra `uv run pytest -q` (+ ruff, mypy) → yeşilse commit.

Başlangıç 01:38'de yapıldı (Faz 1'in saati geçmişti); fazlar kaydırıldı:
Faz 1 ≈ 01:40–02:20 · Faz 2 ≈ 02:20–03:50 · Faz 3 ≈ 03:50–04:40 · Faz 4 ≈ 04:40–05:30 · Faz 5 ≈ 05:30–06:00

## Hazırlık
- [x] Dal: `gece/arayuz-guvenlik` (main'den)
- [x] `.gece/` dosyaları (KURALLAR, PLAN, DURUM, SORULAR, ONERILER)
- [x] Başlangıç testleri → DURUM.md
- [x] Saatlik yeniden başlatma görevi (oturum içi cron)

## Faz 1 — Rakip analizi → `.gece/RAKIP_ANALIZI.md`
- [x] 1.1 Türkiye: üniversitelerin tez şablonları / biçim kontrol süreçleri / araçları (YÖK Tez, enstitü
      şablonları, varsa otomatik kontrol araçları)
- [x] 1.2 Yurt dışı: thesis format checker'lar (üniversite içi araçlar, ticari ürünler)
- [x] 1.3 Word eklentileri ve genel belge biçim denetimi (PerfectIt, Grammarly vb. biçim tarafı, şablon araçları)
- [x] 1.4 Arayüz gözlemleri: güven mesajı, yükleme akışı, rapor sunumu, hata ekranları
- [x] 1.5 Synora'nın farkı + 5–10 somut, uygulanabilir fikir (her biri: neden, nerede, korumalı modül gerekir mi)

## Faz 2 — Arayüz iyileştirme (yalnızca şablon, CSS, statik JS, görünen metin)
Önce mevcut sayfaları oku: base, login, upload, job, error, auth_confirm, login_sent, pricing, _story, _marks.
- [x] 2.1 Envanter: her sayfanın durumu, kırık/eksik noktalar, kontrast ölçümü (CSS renk tokenları → WCAG oranı
      hesaplayan küçük test)
- [x] 2.2 Erişilebilirlik temeli: "içeriğe geç" bağlantısı, `lang="tr"`, form etiketleri, odak görünürlüğü
      (`:focus-visible`), `aria-live` ilerleme bölgesi, `prefers-reduced-motion`
- [x] 2.3 Akış netliği: yükle → işleniyor → rapor → kopya adımlarını gösteren adım göstergesi (rakip fikri)
- [x] 2.4 Boş durum: hiç denetimi olmayan kullanıcıya yol gösteren boş durum ("Henüz denetim yok")
- [x] 2.5 Hata ekranları: error.html (403/404/genel) → ne oldu + ne yapmalı + ana sayfa bağlantısı; iş hatası
      ekranında "ne yapabilirim" listesi
- [x] 2.6 Rapor ekranı: özet kartı (hata/uyarı/düzeltilebilir), "sıradaki adım" kutusu, filtrelerin klavye ile
      kullanımı
- [x] 2.7 Mobil: 360 px'te yatay kaydırma yok, dokunma hedefleri ≥ 44 px
- [x] 2.8 Türkçe metin tutarlılığı (terimler: denetim/rapor/düzeltilmiş kopya/yorumlu kopya; büyük-küçük harf)
- [x] 2.9 Her adımın testi (`tests/web/test_ui.py`): şablon içerikleri, etiketler, kontrast, inline stil/script yok

## Faz 3 — Güvenlik testleri (`tests/security/`)
Korumalı modüllerde kod değişmez; açık → xfail test + ONERILER.md + GUVENLIK_RAPORU.md.
- [x] 3.1 A1 ek: iç içe zip (docx içinde zip bomb part), çok sayıda küçük part + yüksek toplam oran, boş part
      adı, NUL/denetim karakterli adlar, `TargetMode="External"` ilişkiler, `altChunk`/OLE, `.dotm` tipi,
      UTF-16/BOM'lu XXE, parametre entity, yarım kalmış zip (truncated), sahte docx (zip ama Word değil)
- [x] 3.2 Web — giriş bağlantısı: süresi dolmuş token, başka e-postanın token'ı, token tekrar POST, oturum
      süresi dolması, çıkıştan sonra eski çerez
- [x] 3.3 Web — CSRF: tüm POST uç noktaları (login, auth, logout, jobs, delete, roles, recheck, output) CSRF'siz
      reddediliyor mu (parametrik test)
- [x] 3.4 Web — yetki: başkasının işi için tüm uç noktalar (delete dahil) 404; geçersiz job_id biçimi
- [x] 3.5 Web — dosya türü: `.docm` / makrolu / zip olmayan / exe başlıklı içerik → failed + doğru kod;
      Content-Type sahteciliği etkisiz
- [x] 3.6 Web — başlıklar: tüm sayfalarda (hata sayfaları, statik, JSON) CSP/nosniff/XFO; çerez bayrakları
      (HttpOnly, SameSite, Secure üretimde)
- [x] 3.7 Web — hız sınırı: günlük iş sınırı, e-posta başına giriş sınırı; IP başına sınır yoksa → bulgu
- [x] 3.8 XSS: e-posta alanı ve hata mesajlarında kaçış; rol seçiminde HTML enjeksiyonu
- [x] 3.9 `.gece/GUVENLIK_RAPORU.md`

## Faz 4 — Arayüz testi
- [ ] 4.1 Uçtan uca: giriş → yükle → rapor → rol düzelt → yeniden denetle → kopya → sil → çıkış (tek test)
- [ ] 4.2 Her sayfa 200/doğru durum kodu, başlık (`<title>`), tek `<h1>`, `<main>` var
- [ ] 4.3 Bilinmeyen URL / yanlış yöntem → kullanıcı dostu hata sayfası mı?
- [ ] 4.4 JS: app.js'in beklediği `data-*` özniteliklerinin şablonlarda var olduğunu doğrula
- [ ] 4.5 Mobil görünüm: CSS medya sorguları; mümkünse tarayıcıda 375 px ekran görüntüsü (yerel sunucu)
- [ ] 4.6 Bulunan kırıkları düzelt (yalnızca izinli dosyalarda) ya da ONERILER.md

## Faz 5 — Son kontrol
- [ ] 5.1 `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src` temiz
- [ ] 5.2 `git log main..` özeti
- [ ] 5.3 `.gece/SABAH_RAPORU.md`: yapılanlar, yapılamayanlar, sorular, öneriler, nasıl incelenir
