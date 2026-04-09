#!/usr/bin/env python3
"""
Space Invader Alert — surveillance invader-spotter.art
"""

import os
import json
import hashlib
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NEWS_URL         = "https://www.invader-spotter.art/news.php"
STATE_FILE       = "last_seen.json"
STATS_FILE       = "daily_stats.json"

MAX_DAYS = 30  # Seulement les 30 derniers jours

WATCHED_TYPES = [
    "Destruction", "Dégradation", "Ajout",
    "Restauration", "Réactivation", "Alerte",
]

WATCHED_CITIES = [
    "PA", "MARS", "GRN", "LY", "TLS", "LIL", "AVI", "NIM",
    "BAB", "MPL", "ORLN", "AMI", "CAZ", "LCT", "CAPF", "PAU",
]

CITY_NAMES = {
    "PA": "Paris", "MARS": "Marseille", "GRN": "Grenoble",
    "LY": "Lyon", "TLS": "Toulouse", "LIL": "Lille",
    "AVI": "Avignon", "NIM": "Nîmes", "BAB": "Bayonne-Biarritz",
    "MPL": "Montpellier", "ORLN": "Orléans", "AMI": "Amiens",
    "CAZ": "Cazaux", "LCT": "La Ciotat", "CAPF": "Cap Ferret", "PAU": "Pau",
}

EMOJIS = {
    "Destruction": "💥", "Dégradation": "⚠️", "Ajout": "🆕",
    "Restauration": "✅", "Réactivation": "♻️", "Alerte": "🚨",
}

MONTHS_FR = {
    "janvier":"01","février":"02","mars":"03","avril":"04",
    "mai":"05","juin":"06","juillet":"07","août":"08",
    "septembre":"09","octobre":"10","novembre":"11","décembre":"12",
}

# ── Scraping ─────────────────────────────────────────────────────────────────
def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; InvaderBot/1.0)"}
    resp = requests.get(NEWS_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return parse_html(resp.text)


def parse_html(html):
    events = []
    cutoff = datetime.now() - timedelta(days=MAX_DAYS)

    # Trouve toutes les occurrences de mois+année dans le HTML avec leur position
    month_re = re.compile(
        r'(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})',
        re.IGNORECASE
    )
    month_positions = []
    for m in month_re.finditer(html):
        mname = m.group(1).lower()
        year  = m.group(2)
        # Normalise les accents
        mname = mname.replace('é','é').replace('û','û')
        for k in MONTHS_FR:
            if k in mname or mname in k:
                mnum = MONTHS_FR[k]
                break
        else:
            continue
        month_positions.append((m.start(), year, mnum))

    # Extrait les codes invader: lienm("PA05",213) -> PA05_213
    invader_re = re.compile(r'lienm\("([^"]+)",\s*(\d+)\)')

    # Extrait les blocs jour: <b>07 :</b> ... jusqu'au prochain <b>dd :</b>
    day_re = re.compile(
        r'<b>(\d{1,2})\s*:</b>(.*?)(?=<b>\d{1,2}\s*:|$)',
        re.DOTALL
    )

    for day_match in day_re.finditer(html):
        day        = day_match.group(1).zfill(2)
        block_html = day_match.group(2)
        pos        = day_match.start()

        # Détermine mois/année selon la position dans le HTML
        year, mnum = "2026", "01"
        for mpos, my, mm in month_positions:
            if mpos <= pos:
                year, mnum = my, mm

        date_str = f"{year}-{mnum}-{day}"

        # Filtre les dates trop anciennes
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            if event_date < cutoff:
                continue
        except ValueError:
            continue

        # Extrait les invaders du bloc
        invaders = [f"{c}_{n}" for c, n in invader_re.findall(block_html)]
        if not invaders:
            continue

        # Texte brut du bloc
        block_text = re.sub(r'<[^>]+>', ' ', block_html)
        block_text = re.sub(r'\s+', ' ', block_text).strip()

        # Détecte le type d'événement
        etype = None
        for et in ["Destruction","Dégradation","Ajout","Restauration","Réactivation","Alerte"]:
            if et.lower() in block_text.lower() or et[:5].lower() in block_text.lower():
                etype = et
                break
        if not etype:
            continue

        uid = hashlib.md5(
            f"{date_str}|{etype}|{'|'.join(sorted(invaders))}".encode()
        ).hexdigest()[:12]

        events.append({
            "date":     date_str,
            "type":     etype,
            "invaders": invaders,
            "id":       uid,
        })

    print(f"  {len(events)} événements trouvés (30 derniers jours)")
    return events


# ── Filtrage ─────────────────────────────────────────────────────────────────
def get_city_prefix(code):
    """PA05_213 -> PA, MARS_39 -> MARS"""
    m = re.match(r'^([A-Z]+)', code)
    if not m:
        return ""
    return re.sub(r'\d+$', '', m.group(1))


def filter_invaders(event):
    return [
        inv for inv in event["invaders"]
        if get_city_prefix(inv) in WATCHED_CITIES
    ]


def should_notify(event):
    return event["type"] in WATCHED_TYPES and len(filter_invaders(event)) > 0


# ── État persistant ───────────────────────────────────────────────────────────
def load_seen_ids():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids):
    with open(STATE_FILE, "w") as f:
        json.dump(list(ids), f)


# ── Stats quotidiennes ────────────────────────────────────────────────────────
def load_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            stats = json.load(f)
        if stats.get("date") == today:
            return stats
    return {"date": today, "checks": 0, "alerts": 0, "events": []}


def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)


# ── Telegram ─────────────────────────────────────────────────────────────────
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     message,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }, timeout=10)
    resp.raise_for_status()


def city_label(code):
    prefix = get_city_prefix(code)
    return CITY_NAMES.get(prefix, prefix)


def format_message(event, invaders):
    emoji = EMOJIS.get(event["type"], "📍")
    lines = [f"{emoji} <b>{event['type']}</b>  —  {event['date']}"]
    by_city = {}
    for inv in invaders:
        city = city_label(inv)
        by_city.setdefault(city, []).append(inv)
    for city, codes in by_city.items():
        lines.append(f"📍 <b>{city}</b> : {', '.join(codes)}")
        if len(codes) == 1:
            lines.append(f'   🔗 <a href="https://www.invader-spotter.art/news.php">Voir les news</a>')
    if len(invaders) > 1:
        lines.append(f'   🔗 <a href="https://www.invader-spotter.art/news.php">Toutes les news</a>')
    return "\n".join(lines)


def format_daily_summary(stats):
    today = datetime.now().strftime("%d/%m/%Y")
    if stats["alerts"] == 0:
        return (
            f"☀️ <b>Résumé du {today}</b>\n"
            f"✅ Bot actif — {stats['checks']} vérifications\n"
            f"😌 Aucun événement en France aujourd'hui"
        )
    lines = [
        f"📊 <b>Résumé du {today}</b>",
        f"🔍 {stats['checks']} vérifications — {stats['alerts']} alerte(s)",
        "",
    ]
    for e in stats["events"]:
        emoji = EMOJIS.get(e["type"], "📍")
        lines.append(f"{emoji} {e['type']} : {', '.join(e['invaders'])}")
    lines.append(f'\n🔗 <a href="https://www.invader-spotter.art/news.php">Voir toutes les news</a>')
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M}] Vérification des news…")

    stats    = load_stats()
    stats["checks"] += 1

    seen_ids = load_seen_ids()
    events   = fetch_news()

    new_events = [e for e in events if e["id"] not in seen_ids and should_notify(e)]
    print(f"  {len(new_events)} nouveaux événements à notifier.")

    if new_events:
        for event in new_events:
            invaders = filter_invaders(event)
            try:
                send_telegram(format_message(event, invaders))
                stats["alerts"] += 1
                stats["events"].append({"type": event["type"], "invaders": invaders})
                print(f"  ✓ {event['type']} — {invaders}")
            except Exception as ex:
                print(f"  ✗ Erreur Telegram: {ex}")
            seen_ids.add(event["id"])
        save_seen_ids(seen_ids)
    else:
        print("  Rien de nouveau !")

    save_stats(stats)

    # Résumé quotidien à 8h UTC (10h Paris)
    if now.hour == 8:
        print("  Envoi du résumé quotidien…")
        try:
            send_telegram(format_daily_summary(stats))
        except Exception as ex:
            print(f"  ✗ Erreur résumé: {ex}")


if __name__ == "__main__":
    main()
