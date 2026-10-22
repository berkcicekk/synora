# Güvenlik politikası

Payper öğrencilerin tez dosyalarını işler; güvenlik bildirimlerini ciddiye alıyoruz.

## Açık bildirme

Bir güvenlik açığı bulduysanız lütfen **herkese açık issue AÇMAYIN**. Bunun yerine GitHub'ın
özel bildirim kanalını kullanın:

**[Security → Report a vulnerability](https://github.com/berkcicekk/synora/security/advisories/new)**

72 saat içinde dönüş yapmayı hedefliyoruz. Açık doğrulanırsa düzeltme yayımlanana kadar
ayrıntıları birlikte gizli tutar, düzeltmede katkınızı (isterseniz) anarız.

## Kapsam

Özellikle ilgilendiğimiz alanlar: `.docx` ayrıştırma (zip bomb, XXE, path traversal),
tez metninin sızması (log, hata mesajı, rapor), oturum/CSRF/yetki atlamaları ve
kaynak tüketimi (DoS). Mimari ve güvenlik sınırları: `docs/architecture.md` (§2, §8).

Test ortamı olarak kendi kurulumunuzu kullanın; `demo.payper.live` üzerindeki diğer
kullanıcıların işlerine erişmeye çalışmayın.
