# Payper'ı sunucuya kurmak

> Servis, paket ve ortam değişkeni adları tarihsel nedenle `synora`/`SYNORA_*` kalmıştır.

Hedef: Türkiye'de barındırılan bir **Linux** sunucu (Ubuntu 24.04 / Debian 12). Windows üretim için
uygun değildir: iş yürütücüsünün bellek ve CPU sınırları (A10) yalnızca Linux'ta çalışır.

## Dosyalar

| Dosya | Nereye |
|---|---|
| `synora.env.example` | `/etc/synora/synora.env` (izin 600) — tüm ayarlar |
| `synora.service` | `/etc/systemd/system/synora.service` |
| `nginx-synora.conf` | `/etc/nginx/sites-available/synora` (+ içindeki `synora_proxy.conf`) |
| `../compose.yaml`, `../Dockerfile` | Docker ile kurulumda `synora.service` yerine |

## Kurulum

```sh
# uv'yi sistem geneline kurun (ör. /usr/local/bin/uv); servis kullanıcısının PATH'i boştur.
sudo useradd --system --home /opt/synora --shell /usr/sbin/nologin synora
sudo mkdir -p /opt/synora /var/lib/synora /etc/synora
# Kodu /opt/synora'ya alın (git clone ya da arşiv), sonra sahipliği verin:
sudo chown -R synora:synora /opt/synora /var/lib/synora && sudo chmod 700 /var/lib/synora
cd /opt/synora && sudo -u synora -H /usr/local/bin/uv sync --no-dev --frozen
sudo cp deploy/synora.env.example /etc/synora/synora.env && sudo chmod 600 /etc/synora/synora.env
sudo cp deploy/synora.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now synora
curl -s http://127.0.0.1:8000/health
```

## Docker ile (yukarıdakinin yerine)

Sunucuda yalnızca Docker (compose eklentisiyle), nginx ve certbot gerekir; Python ya da uv gerekmez.
`compose.yaml` ve `Dockerfile` repo kökündedir. Kapsayıcı yalnızca `127.0.0.1:8000`'i dinler, kök
dosya sistemi salt okunurdur, `synora` kullanıcısıyla (root değil) ve systemd birimindeki bellek/süreç
sınırlarıyla çalışır. Veritabanı `synora-data` adlı Docker bölümündedir.

```sh
sudo mkdir -p /etc/synora
sudo cp deploy/synora.env.example /etc/synora/synora.env && sudo chmod 600 /etc/synora/synora.env
sudo nano /etc/synora/synora.env          # alan adı, SMTP; DB/kural seti yollarını compose ayarlar
sudo docker compose up -d --build
sudo docker compose ps                    # STATUS: healthy
curl -s http://127.0.0.1:8000/health
```

nginx ayarı (`nginx-synora.conf`) iki kurulumda aynıdır. Yükseltme: `git pull && sudo docker compose
up -d --build`. Kayıtlar: `sudo docker compose logs -f`. `synora.service` bu kurulumda kullanılmaz;
ikisini birden çalıştırmayın (tek süreç kuralı). Uygulama istemci IP'sini kullanmadığından
`FORWARDED_ALLOW_IPS` kapsayıcıda etkisizdir; IP'ye dayalı bir sınır eklenirse Docker ağ geçidi
adresi buraya yazılmalı.

## Kurallar

- **Tek süreç.** `synora serve` tek uvicorn süreci çalıştırır; ikinci bir örnek aynı veritabanını
  kullanırsa birbirinin işlerini "yarıda kaldı" diye kapatır. Ölçeklemek için `SYNORA_WORKERS` artırılır.
- **Tez diske yazılmaz.** nginx'te `proxy_request_buffering off` zorunludur; açık kalırsa nginx yüklenen
  dosyayı geçici dosyaya yazar. Uygulama dosyayı bellekte işler.
- **Kayıtlar.** Uygulama olayları (`job.done`, `retention.purged`…) standart çıktıya JSON olarak yazılır,
  `journalctl -u synora` (Docker'da `docker compose logs`) ile okunur; tez metni içermez. Üretimde uvicorn erişim kaydı kapalıdır, nginx
  erişim kaydı sorgu dizesini yazmaz ve hata kaydı yalnızca ciddi hataları tutar (giriş bağlantısı
  sızmasın).
- **Sağlık.** `/health` veritabanı ya da iş yürütücü sorunluysa 503 döner; izleme bunu denetlemeli.
- **Yükseltme.** Günlük iş sayacı (Ö5) yükseltmeden sonra boş başlar; ilk 24 saatte herkesin günlük
  kotası yenilenmiş olur.
- **Yedek.** Veritabanında kalıcı olan yalnızca kayıt onaylarıdır (`users` tablosu). İşler ve raporlar
  24 saatte silinir; yedekler bu silmeyi geri getirmemeli. Demo sunucusundaki uygulama: günlük cron,
  `jobs`/`sessions`/`login_tokens`/`feedback` tabloları **silinerek** yedeklenir, 7 gün saklanır.
- **SMTP.** Giriş bağlantıları için gerçek bir SMTP hesabı gerekir (sağlayıcı `[KARAR?]`); kurulumdan
  sonra kendi adresinize giriş bağlantısı isteyerek deneyin.
