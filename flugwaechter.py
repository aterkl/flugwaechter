#!/usr/bin/env python3
"""
Flugwächter – Skyscanner Deutschland → İstanbul fiyat takipçisi.

Her çalıştırmada config.json'daki her tarih için Skyscanner'ın
"Abflugort auswählen" sayfasını açar, tüm Alman şehirlerinin
"Flüge ab" fiyatlarını okur ve eşik altındaki fiyatlar için bildirim yollar.

Kullanım:
  python flugwaechter.py              # normal kontrol (timer bunu çağırır)
  python flugwaechter.py --setup      # tarayıcıyı görünür açar: çerez/captcha'yı elle geç
  python flugwaechter.py --test-notify  # bildirimlerin çalıştığını dene
  python flugwaechter.py --dry-run    # fiyatları yazdır, bildirim gönderme
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "state.json"
HISTORY_FILE = BASE / "prices.csv"
PROFILE_DIR = BASE / "browser-profile"
DEBUG_DIR = BASE / "debug"

PRICE_RE = re.compile(r"^(\d{1,3}(?:[.  ]\d{3})*|\d+)\s*€$")
NOISE = {"Flüge ab", "Direkt", "Abflugort auswählen", "Filter", "Zwischenstopps",
         "Flugbudget", "Filter zurücksetzen"}
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
BLOCK_MARKERS = ("captcha", "bist du ein mensch", "are you a person",
                 "sind sie ein mensch", "press & hold", "gedrückt halten")


# ---------------------------------------------------------------- yardımcılar
def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def tr_date(day: dt.date) -> str:
    return f"{day.day} {AYLAR[day.month - 1]} {GUNLER[day.weekday()]}"


def ablative(city: str) -> str:
    """Köln -> Köln'den, Dortmund -> Dortmund'dan, Düsseldorf -> Düsseldorf'tan."""
    word = city.split()[-1].lower()
    vowels = [c for c in word if c in "aıoueiöüä"]
    back = bool(vowels) and vowels[-1] in "aıou"
    d = "t" if word[-1] in "fstkçşhp" else "d"
    return f"{city}'{d}{'a' if back else 'e'}n"


def stops_tr(stops: str) -> str:
    if stops == "Direkt":
        return "direkt uçuş"
    if "Zwischenstopp" in stops:
        return "aktarmalı"
    return ""


def search_url(cfg: dict, day: dt.date) -> str:
    return (f"https://www.skyscanner.de/transport/fluge/{cfg['origin']}/{cfg['destination']}/"
            f"{day:%y%m%d}/?adultsv2=1&cabinclass=economy&childrenv2=&rtn=0"
            f"&preferdirects=false&outboundaltsenabled=false&inboundaltsenabled=false")


# ---------------------------------------------------------------- ayrıştırma
def parse_cards(text: str) -> dict[str, dict]:
    """Sayfa metninden {şehir: {'price': int, 'stops': str}} çıkarır.

    Kartlar metinde şu sırayla görünür: Şehir / Flüge ab / 113 € / Direkt.
    Sıra biraz değişse de çalışsın diye fiyat satırından geriye doğru
    'gürültü olmayan' ilk satırı şehir adı kabul ediyoruz.
    """
    text = re.sub(r"(\d)\s*\n\s*€", r"\1 €", text)          # "113\n€" -> "113 €"
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out: dict[str, dict] = {}
    for i, line in enumerate(lines):
        m = PRICE_RE.match(line)
        if not m:
            continue
        price = int(re.sub(r"\D", "", m.group(1)))
        city = None
        for j in range(i - 1, max(i - 5, -1), -1):
            cand = lines[j]
            if cand in NOISE or PRICE_RE.match(cand) or "Zwischenstopp" in cand:
                continue
            city = cand
            break
        if not city or len(city) > 40:
            continue
        stops = ""
        for k in list(range(i + 1, min(i + 3, len(lines)))) + list(range(i - 1, max(i - 4, -1), -1)):
            if lines[k] == "Direkt" or "Zwischenstopp" in lines[k]:
                stops = lines[k]
                break
        if city not in out or price < out[city]["price"]:
            out[city] = {"price": price, "stops": stops}
    return out


# ---------------------------------------------------------------- bildirim
def notify(cfg: dict, title: str, message: str, click: str | None = None, priority: int = 4) -> None:
    topic = cfg.get("ntfy_topic", "").strip()
    if topic:
        payload = {"topic": topic, "title": title, "message": message,
                   "priority": priority, "tags": ["airplane"]}
        if click:
            payload["click"] = click
        req = urllib.request.Request(cfg.get("ntfy_server", "https://ntfy.sh"),
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:  # noqa: BLE001
            log(f"ntfy hatası: {e}")
    if cfg.get("desktop_notify", True) and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Flugwächter", "-u", "critical", title, message],
                       check=False)
    log(f"BİLDİRİM: {title} | {message}")


# ---------------------------------------------------------------- tarayıcı
def open_context(pw, cfg: dict, headless: bool):
    PROFILE_DIR.mkdir(exist_ok=True)
    kwargs = dict(user_data_dir=str(PROFILE_DIR), headless=headless, locale="de-DE",
                  timezone_id="Europe/Berlin", viewport={"width": 1366, "height": 900})
    if cfg.get("browser_executable"):
        kwargs["executable_path"] = cfg["browser_executable"]
    else:
        kwargs["channel"] = "chromium"   # "yeni" headless modu, daha az engelleniyor
    return pw.chromium.launch_persistent_context(**kwargs)


def is_blocked(page) -> bool:
    if "captcha" in page.url.lower():
        return True
    try:
        body = page.inner_text("body", timeout=5000).lower()
    except Exception:  # noqa: BLE001
        return False
    return any(m in body for m in BLOCK_MARKERS) and "flüge ab" not in body


def fetch_day(page, cfg: dict, day: dt.date) -> dict[str, dict] | None:
    url = search_url(cfg, day)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("text=Flüge ab", timeout=45000)
    except Exception:  # noqa: BLE001
        pass
    if is_blocked(page):
        return None
    # Tüm kartların yüklenmesi için aşağı kaydır / "Mehr anzeigen"e bas
    for _ in range(8):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(700)
        more = page.locator("button:has-text('Mehr anzeigen')")
        if more.count() and more.first.is_visible():
            more.first.click()
            page.wait_for_timeout(1500)
    page.wait_for_timeout(1500)
    cards = parse_cards(page.inner_text("body"))
    if not cards:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = f"{day:%m%d}_{dt.datetime.now():%H%M%S}"
        page.screenshot(path=str(DEBUG_DIR / f"{stamp}.png"), full_page=True)
        (DEBUG_DIR / f"{stamp}.txt").write_text(page.inner_text("body"), encoding="utf-8")
        log(f"{day}: fiyat okunamadı, debug/{stamp}.* kaydedildi")
    return cards


# ---------------------------------------------------------------- ana akış
def run(cfg: dict, dry_run: bool) -> int:
    from playwright.sync_api import sync_playwright

    today = dt.date.today()
    days = [d for d in (dt.date.fromisoformat(s) for s in cfg["dates"]) if d >= today]
    if not days:
        log("Takip edilecek tarih kalmadı. Timer'ı kapatabilirsin.")
        return 0

    state = load_json(STATE_FILE, {})
    state.setdefault("notified", {})
    state.setdefault("last_seen", {})
    state.setdefault("blocked_notified", "")
    threshold = cfg["threshold_eur"]
    new_hits = []
    blocked = False

    with sync_playwright() as pw:
        ctx = open_context(pw, cfg, headless=cfg.get("headless", True))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for n, day in enumerate(days):
            if n:
                time.sleep(random.uniform(5, 12))   # siteyi yormamak için
            try:
                cards = fetch_day(page, cfg, day)
            except Exception as e:  # noqa: BLE001
                log(f"{day}: hata: {e}")
                continue
            if cards is None:
                blocked = True
                log(f"{day}: Skyscanner doğrulama (captcha) istiyor, durduruluyor.")
                break
            cheapest = min(cards.items(), key=lambda kv: kv[1]["price"], default=None)
            log(f"{day}: {len(cards)} şehir, en ucuz: "
                f"{cheapest[0]} {cheapest[1]['price']} €" if cheapest else f"{day}: veri yok")
            with HISTORY_FILE.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                for city, info in cards.items():
                    w.writerow([dt.datetime.now().isoformat(timespec="minutes"),
                                day.isoformat(), city, info["price"], info["stops"]])
            for city, info in cards.items():
                key = f"{day.isoformat()}|{city}"
                previous = state["last_seen"].get(key)
                state["last_seen"][key] = info["price"]
                if info["price"] >= threshold:
                    continue
                last = state["notified"].get(key)
                if last is None or info["price"] < last:   # yalnızca yeni / daha ucuz
                    new_hits.append((day, city, info, previous, search_url(cfg, day)))
                    state["notified"][key] = info["price"]
        ctx.close()

    new_hits.sort(key=lambda h: h[2]["price"])
    for day, city, info, previous, url in new_hits[:8]:
        title = f"🔻 İndirim: {day.day} {AYLAR[day.month - 1]} – {city} → İstanbul"
        msg = f"{tr_date(day)} günü {ablative(city)} kalkan uçak {info['price']} €'ya düştü"
        extra = []
        if previous and previous > info["price"]:
            extra.append(f"önceki: {previous} €")
        if stops_tr(info["stops"]):
            extra.append(stops_tr(info["stops"]))
        if extra:
            msg += f" ({', '.join(extra)})"
        msg += "."
        if dry_run:
            log(f"[dry-run] {title} | {msg}")
        else:
            notify(cfg, title, msg, click=url, priority=5)
    if len(new_hits) > 8 and not dry_run:
        notify(cfg, f"🔻 {len(new_hits) - 8} indirim daha var",
               "Tüm liste için prices.csv dosyasına bak.", priority=3)
    if dry_run:
        return 0

    if blocked and state.get("blocked_notified") != today.isoformat():
        notify(cfg, "Flugwächter: Skyscanner doğrulama istiyor",
               "Terminalde 'python flugwaechter.py --setup' çalıştırıp doğrulamayı elle geç.",
               priority=3)
        state["blocked_notified"] = today.isoformat()

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def setup(cfg: dict) -> None:
    """Görünür tarayıcı açar; çerez bannerını ve varsa doğrulamayı kendin geçersin."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = open_context(pw, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(search_url(cfg, dt.date.fromisoformat(cfg["dates"][0])))
        input("Tarayıcıda çerez seçimini yap / doğrulamayı geç, fiyatlar görününce Enter'a bas… ")
        cards = parse_cards(page.inner_text("body"))
        print(f"{len(cards)} şehir okundu:")
        for city, info in sorted(cards.items(), key=lambda kv: kv[1]["price"]):
            print(f"  {city:<25} {info['price']:>5} €  {info['stops']}")
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_json(CONFIG_FILE, None)
    if cfg is None:
        sys.exit("config.json bulunamadı.")
    # GitHub Actions gibi ortamlarda ayarları ortam değişkeniyle ez
    import os
    if os.environ.get("NTFY_TOPIC"):
        cfg["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    if os.environ.get("CI"):
        cfg["headless"] = True
        cfg["desktop_notify"] = False
    if args.test_notify:
        notify(cfg, "Flugwächter test", "Bildirimler çalışıyor ✅")
        return 0
    if args.setup:
        setup(cfg)
        return 0
    return run(cfg, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
