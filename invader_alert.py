#!/usr/bin/env python3
"""
Space Invader Alert — surveillance invader-spotter.art
Tous pays, format minimaliste.
"""

import os
import json
import hashlib
import re
import requests
from datetime import datetime, timedelta

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NEWS_URL         = "https://www.invader-spotter.art/news.php"
STATE_FILE       = "last_seen.json"
STATS_FILE       = "daily_stats.json"

MAX_DAYS = 30

WATCHED_TYPES = [
    "Destruction", "Dégradation", "Ajout",
    "Restauration", "Réactivation", "Alerte",
]

# Tous les pays — dictionnaire des codes connus
CITY_NAMES = {
    # France
    "PA": "Paris 🇫🇷", "MARS": "Marseille 🇫🇷", "GRN": "Grenoble 🇫🇷",
    "LY": "Lyon 🇫🇷", "TLS": "Toulouse 🇫🇷", "LIL": "Lille 🇫🇷",
    "AVI": "Avignon 🇫🇷", "NIM": "Nîmes 🇫🇷", "BAB": "Bayonne 🇫🇷",
    "MPL": "Montpellier 🇫🇷", "ORLN": "Orléans 🇫🇷", "AMI": "Amiens 🇫🇷",
    "CAZ": "Cazaux 🇫🇷", "LCT": "La Ciotat 🇫🇷", "CAPF": "Cap Ferret 🇫🇷",
    "PAU": "Pau 🇫🇷", "FTBL": "Fontainebleau 🪨",
    # International
    "LDN": "Londres 🇬🇧", "NCL": "Newcastle 🇬🇧", "MAN": "Manchester 🇬🇧",
    "NY": "New York 🇺🇸", "LA": "Los Angeles 🇺🇸", "MIA": "Miami 🇺🇸",
    "SD": "San Diego 🇺🇸", "RDU": "Raleigh 🇺🇸",
    "HK": "Hong Kong 🇭🇰",
    "TK": "Tokyo 🇯🇵",
    "BGK": "Bangkok 🇹🇭",
    "ROM": "Rome 🇮🇹", "VRN": "Vérone 🇮🇹", "MLN": "Milan 🇮🇹",
    "SP": "Madrid 🇪🇸", "BCN": "Barcelone 🇪🇸",
    "BXL": "Bruxelles 🇧🇪",
    "AMS": "Amsterdam 🇳🇱",
    "BRL": "Berlin 🇩🇪", "MUN": "Munich 🇩🇪",
    "GNV": "Genève 🇨🇭", "BSL": "Bâle 🇨🇭",
    "LJU": "Ljubljana 🇸🇮",
    "IST": "Istanbul 🇹🇷",
    "SL": "Séoul 🇰🇷",
    "MLB": "Melbourne 🇦🇺",
    "BTA": "Bogota 🇨🇴",
    "RBA": "Rabat 🇲🇦",
    "KAT": "Katmandou 🇳🇵",
    "LSN": "Lisbonne 🇵🇹", "PRT": "Porto 🇵🇹",
    "BBO": "Biarritz 🇫🇷",
    "WN": "Vienne 🇦🇹",
    "CLR": "Clermont 🇫🇷",
    "DJN": "Dijon 🇫🇷",
    "DJBA": "Djibouti 🇩🇯",
    "BRN": "Berne 🇨🇭",
    "MARS": "Marseille 🇫🇷",
}

EMOJIS = {
    "Destruction": "🔴", "Dégradation": "🟠", "Ajout": "🟢",
    "Restauration": "🔵", "Réactivation": "🟣", "Alerte": "🟡",
}

MONTHS_FR_LONG = {
    "01": "janvier", "02": "février", "03": "mars", "04": "avril",
    "05": "mai", "06": "juin", "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
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

    month_re = re.compile(
        r'(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})',
        re.IGNORECASE
    )
    month_positions = []
    for m in month_re.finditer(html):
        mname = m.group(1).lower()
        year  = m.group(2)
        for k in MONTHS_FR:
            if k[:4] in mname or mname[:4] in k:
                mnum = MONTHS_FR[k]
                break
        else:
            continue
        month_positions.append((m.start(), year, mnum))

    invader_re = re.compile(r'lienm\("([^"]+)",\s*(\d+)\)')
    day_re = re.compile(
        r'<b>(\d{1,2})\s*:</b>(.*?)(?=<b>\d{1,2}\s*:|$)',
        re.DOTALL
    )

    for day_match in day_re.finditer(html):
        day        = day_match.group(1).zfill(2)
        block_html = day_match.group(2)
        pos        = day_match.start()

        year, mnum = "2026", "01"
        for mpos, my, mm in month_positions:
            if mpos <= pos:
                year, mnum = my, mm

        date_str = f"{year}-{mnum}-{day}"

        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            if event_date < cutoff:
                continue
        except ValueError:
            continue

        invaders = [f"{c}_{n}" for c, n in invader_re.findall(block_html)]
        if not invaders:
            continue

        block_text = re.sub(r'<[^>]+>', ' ', block_html)
        block_text = re.sub(r'\s+', ' ', block_text).strip()

        etype = None
        for et in ["Destruction","Dégradation","Ajout","Restauration","Réactivation","Alerte"]:
            if et[:5].lower() in block_text.lower():
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


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_city_prefix(code):
    m = re.match(r'^([A-Z]+)', code)
    if not m:
        return ""
    return re.sub(r'\d+$', '', m.group(1))


def city_label(code):
    prefix = get_city_prefix(code)
    return CITY_NAMES.get(prefix, prefix)


def format_date(date_str):
    try:
        y, m, d = date_str.split("-")
        return f"{int(d)} {MONTHS_FR_LONG[m]} {y}"
    except Exception:
        return date_str


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


def format_message(event):
    emoji     = EMOJIS.get(event["type"], "📍")
    invaders  = event["invaders"]
    codes_str = ", ".join(invaders)
    city      = city_label(invaders[0]) if invaders else "?"
    date      = format_date(event["date"])

    return (
        f"{emoji} <b>{event['type']}</b>\n"
        f"{codes_str}\n"
        f"{city} · {date}\n"
        f'🔗 <a href="https://www.invader-spotter.art/news.php">Voir les news</a>'
    )


def format_daily_summary(stats):
    today = datetime.now().strftime("%d/%m/%Y")
    if stats["alerts"] == 0:
        return (
            f"☀️ <b>Résumé du {today}</b>\n"
            f"✅ {stats['checks']} vérifications — aucun événement"
        )
    lines = [f"📊 <b>Résumé du {today}</b>",
             f"🔍 {stats['checks']} vérifications — {stats['alerts']} alerte(s)", ""]
    for e in stats["events"]:
        emoji = EMOJIS.get(e["type"], "📍")
        lines.append(f"{emoji} {e['type']} : {', '.join(e['invaders'])}")
    lines.append(f'\n🔗 <a href="https://www.invader-spotter.art/news.php">Toutes les news</a>')
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M}] Vérification des news…")

    stats = load_stats()
    stats["checks"] += 1

    seen_ids = set()
    events   = fetch_news()

    new_events = [e for e in events if e["id"] not in seen_ids]
    print(f"  {len(new_events)} nouveaux événements à notifier.")

    if new_events:
        for event in new_events:
            try:
                send_telegram(format_message(event))
                stats["alerts"] += 1
                stats["events"].append({"type": event["type"], "invaders": event["invaders"]})
                print(f"  ✓ {event['type']} — {event['invaders']}")
            except Exception as ex:
                print(f"  ✗ Erreur Telegram: {ex}")
            seen_ids.add(event["id"])
        save_seen_ids(seen_ids)
    else:
        print("  Rien de nouveau !")

    save_stats(stats)

    if now.hour == 6:
        print("  Envoi du résumé quotidien…")
        try:
            send_telegram(format_daily_summary(stats))
        except Exception as ex:
            print(f"  ✗ Erreur résumé: {ex}")


if __name__ == "__main__":
    main()
