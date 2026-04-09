#!/usr/bin/env python3
"""
Space Invader Alert — surveillance invader-spotter.art
"""

import os
import json
import hashlib
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NEWS_URL         = "https://www.invader-spotter.art/news.php"
STATE_FILE       = "last_seen.json"
STATS_FILE       = "daily_stats.json"

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
    soup = BeautifulSoup(resp.text, "html.parser")
    return parse_events(soup)


def parse_events(soup):
    events = []
    current_year_month = None

    # Les news sont dans des balises <b> pour les jours
    # et les invaders sont dans des liens javascript:lienm("XX",YY)
    # On extrait directement depuis le HTML brut

    html = str(soup)

    # Extrait tous les codes invader depuis les appels javascript
    # Format: javascript:lienm("PA",1562) -> PA_1562
    # On garde aussi le contexte autour pour détecter le type d'événement

    # Cherche les blocs de mois
    month_pattern = re.compile(
        r'(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})',
        re.IGNORECASE
    )

    # Cherche les lignes de news avec leur jour
    # Format dans le HTML: <b>07 :</b> texte avec lienm(...)
    day_pattern = re.compile(
        r'<b>(\d{1,2})\s*:</b>\s*([^<\n]*(?:<[^>]+>[^<\n]*)*?)(?=<b>\d|$)',
        re.DOTALL
    )

    # Extrait les codes depuis javascript:lienm("CODE",NUM)
    invader_pattern = re.compile(r'lienm\("([A-Z0-9]+)",(\d+)\)')

    # Traitement ligne par ligne du texte brut
    lines = soup.get_text("\n").splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Détecte mois/année
        for mname, mnum in MONTHS_FR.items():
            if mname in line.lower():
                for y in range(2020, 2031):
                    if str(y) in line:
                        current_year_month = (str(y), mnum)
                        break

        # Détecte une ligne de news
        m = re.match(r'^(\d{1,2})\s*:\s*(.+)$', line)
        if m and current_year_month:
            day  = m.group(1).zfill(2)
            rest = m.group(2).strip()
            year, month = current_year_month
            date_str = f"{year}-{month}-{day}"
            events.extend(parse_event_line(rest, date_str))

    # Si toujours 0 événements, essaie avec le HTML brut
    if len(events) == 0:
        print("  Tentative parsing HTML brut...")
        current_year_month = None

        for mname, mnum in MONTHS_FR.items():
            positions = [m.start() for m in re.finditer(mname, html, re.IGNORECASE)]
            for pos in positions:
                context = html[pos:pos+20]
                for y in range(2020, 2031):
                    if str(y) in context:
                        current_year_month = (str(y), mnum)

        # Cherche tous les patterns lienm dans le HTML
        all_invaders = invader_pattern.findall(html)
        print(f"  Invaders trouvés dans le HTML: {len(all_invaders)}")

        # Cherche les blocs jour dans le HTML
        blocks = re.findall(
            r'<b>(\d{1,2})\s*:</b>(.*?)(?=<b>\d{1,2}\s*:|<br\s*/?>[\s\S]{0,20}<b>|$)',
            html, re.DOTALL
        )
        print(f"  Blocs jour trouvés: {len(blocks)}")

        if current_year_month and blocks:
            year, month = current_year_month
            for day, block_html in blocks[:10]:  # derniers 10 jours
                date_str = f"{year}-{month}-{day.zfill(2)}"
                # Extrait le texte du bloc
                block_text = re.sub(r'<[^>]+>', ' ', block_html)
                block_text = re.sub(r'\s+', ' ', block_text).strip()
                # Extrait les codes invader du bloc
                inv_matches = invader_pattern.findall(block_html)
                invaders = [f"{code}_{num}" for code, num in inv_matches]
                if invaders and block_text:
                    events.extend(parse_event_line_with_invaders(block_text, invaders, date_str))

    print(f"  {len(events)} événements trouvés au total")
    return events


def parse_event_line(text, date_str):
    """Parse une ligne texte et extrait les invaders via regex."""
    event_keywords = {
        "Destruction":  r"Destruction",
        "Dégradation":  r"Dégradation",
        "Ajout":        r"Ajout",
        "Restauration": r"Restauration",
        "Réactivation": r"Réactivation",
        "Alerte":       r"Alerte",
    }
    results  = []
    segments = re.split(r"\.\s+(?=[A-ZÀÂÉ])", text)

    for segment in segments:
        etype = None
        for et, pattern in event_keywords.items():
            if re.search(pattern, segment, re.IGNORECASE):
                etype = et
                break
        if not etype:
            continue
        # Codes format XX_123 dans le texte
        invaders = re.findall(r'\b([A-Z]{1,6}_\d+)\b', segment)
        if not invaders:
            continue
        uid = hashlib.md5(
            f"{date_str}|{etype}|{'|'.join(sorted(invaders))}".encode()
        ).hexdigest()[:12]
        results.append({"date": date_str, "type": etype, "invaders": invaders, "id": uid})

    return results


def parse_event_line_with_invaders(text, invaders, date_str):
    """Parse avec des invaders déjà extraits du HTML."""
    event_keywords = {
        "Destruction":  r"Destruction",
        "Dégradation":  r"Dégradation",
        "Ajout":        r"Ajout",
        "Restauration": r"Restauration",
        "Réactivation": r"Réactivation",
        "Alerte":       r"Alerte",
    }
    etype = None
    for et, pattern in event_keywords.items():
        if re.search(pattern, text, re.IGNORECASE):
            etype = et
            break
    if not etype or not invaders:
        return []

    uid = hashlib.md5(
        f"{date_str}|{etype}|{'|'.join(sorted(invaders))}".encode()
    ).hexdigest()[:12]
    return [{"date": date_str, "type": etype, "invaders": invaders, "id": uid}]


# ── Filtrage ─────────────────────────────────────────────────────────────────
def get_city_code(invader_code):
    m = re.match(r'^([A-Z]+)_', invader_code)
    return m.group(1) if m else ""

def filter_invaders(event):
    return [
        inv for inv in event["invaders"]
        if any(get_city_code(inv).startswith(city) for city in WATCHED_CITIES)
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

def city_label(invader_code):
    code = get_city_code(invader_code)
    for city in sorted(CITY_NAMES.keys(), key=len, reverse=True):
        if code.startswith(city):
            return CITY_NAMES[city]
    return code

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
            url = f"https://www.invader-spotter.art/mosaic.php?id={codes[0]}"
            lines.append(f'   🔗 <a href="{url}">Voir sur le site</a>')
    if len(invaders) > 1:
        lines.append(f'   🔗 <a href="https://www.invader-spotter.art/news.php">Toutes les news</a>')
    return "\n".join(lines)

def format_daily_summary(stats):
    today = datetime.now().strftime("%d/%m/%Y")
    if stats["alerts"] == 0:
        return (
            f"☀️ <b>Résumé du {today}</b>\n"
            f"✅ Bot actif — {stats['checks']} vérifications effectuées\n"
            f"😌 Aucun événement en France aujourd'hui"
        )
    else:
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

    stats = load_stats()
    stats["checks"] += 1

    seen_ids   = load_seen_ids()
    seen_ids = set()  # TEMP: force toutes les notifs
    events         = fetch_news()
    for e in events:
        print(f"  EVENT: {e['type']} {e['invaders']} {e['date']}")
    new_events = [e for e in events if e["id"] not in seen_ids and should_notify(e)]

    print(f"  {len(new_events)} nouveaux événements à notifier.")

    if new_events:
        for event in new_events:
            invaders = filter_invaders(event)
            send_telegram(format_message(event, invaders))
            seen_ids.add(event["id"])
            stats["alerts"] += 1
            stats["events"].append({"type": event["type"], "invaders": invaders})
            print(f"  ✓ {event['type']} — {invaders}")
        save_seen_ids(seen_ids)
    else:
        print("  Rien de nouveau !")

    save_stats(stats)

    # Résumé quotidien à 8h00 UTC (10h00 Paris)
    if now.hour == 8:
        print("  Envoi du résumé quotidien…")
        send_telegram(format_daily_summary(stats))

if __name__ == "__main__":
    main()
