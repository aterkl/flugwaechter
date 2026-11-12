# Flugwächter ✈️ — Deutschland → İstanbul fiyat alarmı

18–23 Aralık arasındaki her gün için Skyscanner'ın "Deutschland → Istanbul (alle)"
sayfasını açar, tüm kalkış şehirlerinin fiyatlarını okur. **70 €'nun altına düşen**
bir fiyat görürse telefonuna (ntfy) ve Fedora masaüstüne bildirim gönderir.

Örnek bildirim:
> **🔻 İndirim: 19 Aralık – Köln → İstanbul**
> 19 Aralık Cumartesi günü Köln'den kalkan uçak 65 €'ya düştü (önceki: 89 €, direkt uçuş).

İki şekilde çalıştırabilirsin: **A) GitHub Actions** (internette, bilgisayar kapalıyken de çalışır) veya **B) kendi Fedora'nda**.

- Aynı tarih ve şehir için tekrar bildirim göndermez. Yalnızca fiyat daha da düşerse yeniden haber verir.
- Kendi bilgisayarında çalıştırırsan okunan tüm fiyatlar `prices.csv` dosyasına da kaydedilir.
- 23 Aralık geçince kendiliğinden durur.

## A) GitHub Actions ile internette çalıştırma (15 dakikada bir)

1. GitHub'da **public** bir depo oluştur, örn. `flugwaechter`. Public depolarda Actions ücretsiz ve sınırsızdır. 15 dakikada bir çalışma ayda ~10.000 dakika eder; private depolarda ücretsiz kota 2.000 dakika.
2. Bu klasörün içeriğini depoya yükle (`.github/` klasörü dahil):
   ```bash
   cd ~/flugwaechter
   git init && git add . && git commit -m "Flugwächter"
   git branch -M main
   git remote add origin git@github.com:KULLANICI_ADIN/flugwaechter.git
   git push -u origin main
   ```
3. Depoda **Settings → Secrets and variables → Actions → New repository secret**: adı `NTFY_TOPIC`, değeri ntfy konun (aşağıdaki 2. adıma bak).
4. **Actions** sekmesi → *Flugwächter* → **Run workflow** ile ilk çalıştırmayı elle başlat ve logları kontrol et.
   - Logda `… şehir, en ucuz: …` görüyorsan her şey çalışıyor demektir.
   - `doğrulama (captcha) istiyor` görüyorsan Skyscanner GitHub sunucularını engelliyor demektir. Bu durumda B seçeneğini kullan; ev internetinden gelen istekler çok daha az engellenir.
   - `fiyat okunamadı` görüyorsan çalıştırmanın altındaki **debug** dosyasını indirip Claude Code'a göster.

Notlar:
- GitHub, yoğun saatlerde zamanlanmış çalıştırmaları birkaç dakika geciktirebilir. 15 dakika yaklaşık bir aralıktır.
- Hangi fiyatların zaten bildirildiği `state.json` dosyasında tutulur ve her çalıştırmadan sonra depoya kaydedilir.
- Durdurmak için: Actions → Flugwächter → **⋯ → Disable workflow**.

## B) Kendi bilgisayarında çalıştırma

## 1. Kurulum (Fedora)

```bash
# Dosyaları ~/flugwaechter klasörüne koy
cd ~/flugwaechter
python3 -m venv .venv
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

## 2. Telefon bildirimleri (ntfy)

1. Galaxy'ne Play Store'dan **ntfy** uygulamasını kur.
2. Uygulamada **+** ile tahmin edilmesi zor bir konuya abone ol, örn. `emre-flug-8k3x9q`.
3. Aynı adı `config.json` içindeki `"ntfy_topic"` alanına yaz.
4. Test et:
   ```bash
   .venv/bin/python flugwaechter.py --test-notify
   ```

> ntfy.sh konuları herkese açıktır. Konu adını bilen herkes mesajları görebilir, bu yüzden rastgele bir ad seç.

## 3. İlk çalıştırma (çerez + olası doğrulama)

```bash
.venv/bin/python flugwaechter.py --setup
```
Bir tarayıcı penceresi açılır. Çerez seçimini yap, doğrulama çıkarsa kendin geç.
Fiyatlar görününce terminalde Enter'a bas. Okunan şehir listesi ekrana yazdırılır.
Tarayıcı profili `browser-profile/` klasöründe saklanır, sonraki çalıştırmalar bunu kullanır.

Ardından bildirim göndermeden deneme yap:
```bash
.venv/bin/python flugwaechter.py --dry-run
```

## 4. 15 dakikada bir otomatik çalıştırma (systemd user timer)

```bash
mkdir -p ~/.config/systemd/user
cp flugwaechter.service flugwaechter.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now flugwaechter.timer

systemctl --user list-timers | grep flug       # bir sonraki çalışma zamanı
journalctl --user -u flugwaechter -f           # loglar
```
Kapatmak için: `systemctl --user disable --now flugwaechter.timer`

## Ayarlar (`config.json`)

| Alan | Anlamı |
|---|---|
| `dates` | Takip edilen günler |
| `threshold_eur` | Bildirim eşiği (70) |
| `destination` | `ista` = İstanbul tüm havalimanları (IST + SAW) |
| `headless` | `true` olursa tarayıcı görünmez. Skyscanner sürekli engellerse `false` yap |
| `browser_executable` | İstersen kendi Chromium/Brave yolun, örn. `/usr/bin/brave-browser` |

## Sorun giderme

- **"Skyscanner doğrulama istiyor" bildirimi:** `--setup` komutunu çalıştırıp doğrulamayı elle geç. Bu bildirim günde en fazla bir kez gelir. Sorun sık tekrarlanırsa `headless` ayarını `false` yap.
- **"fiyat okunamadı":** Skyscanner sayfa düzenini değiştirmiş olabilir. `debug/` klasöründeki ekran görüntüsünü ve metin dosyasını Claude Code'a göster.
- "Flüge ab" fiyatları Skyscanner'ın önbellekteki tahmini fiyatlarıdır. Bildirim geldiğinde bağlantıyı açıp güncel fiyatı kontrol et.
