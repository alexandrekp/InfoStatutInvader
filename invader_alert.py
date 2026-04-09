#!/usr/bin/env python3
"""
Space Invader Alert — surveillance invader-spotter.art
Envoie une notification Telegram pour chaque nouvel événement détecté.
Filtres actifs : villes françaises / tous types d'événements.
"""

import os
import json
import hashlib
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ── Configuration ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NEWS_URL         = "https://www.invader-spotter.art/news.php"
STATE_FILE       = "last_seen.json"

# Types d'événements surveillés
WATCHED_TYPES = [
    "Destruction",
    "Dégradation",
    "Ajout",
    "Restauration",
    "Réactivation",
    "Alerte",
]

# Villes françaises surveillées (préfixes des codes invader)
WATCHED_CITIES = [
    "PA",    # Paris (PA01–PA20 + banlieue PA92–PA95)
    "MARS",  # Marseille
    "GRN",   # Grenoble
    "LY",    # Lyon
    "TLS",   # Toulouse
    "LIL",   # Lille
    "AVI",   # Avignon
    "NIM",   # Nîmes
    "BAB",   # Bayonne-Anglet-Biarritz
    "MPL",   # Montpellier
    "ORLN",  # Orléans
    "AMI",   # Amiens
    "CAZ",   # Cazaux
    "LCT",   # La Ciotat
    "CAPF",  # Cap Ferret
    "PAU",   # Pau
]

# Noms lisibles par préfixe ville
CITY_NAMES = {
    "PA":    "Paris",
    "MARS":  "Marseille",
    "GRN":   "Grenoble",
    "LY":    "Lyon",
    "TLS":   "Toulouse",
    "LIL":   "Lille",
    "AVI":   "Avignon",
    "NIM":   "Nîmes",
    "BAB":   "Bayonne-Biarritz",
    "MPL":   "Montpellier",
    "ORLN":  "Orléans",
    "AMI":   "Amiens",
    "CAZ":   "Cazaux",
    "LCT":   "La Ciotat",
    "CAPF":  "Cap Ferret",
    "PAU":   "Pau",
}

EMOJIS = {
    "Destruction":  "💥",
    "Dégradation":  "⚠️",
    "Ajout":        "🆕",
    "Restauration": "✅",
    "Réactivation": "♻️",
    "Alerte":       "🚨",
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
    raw_text = soup.get_text("\n")
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    months_fr = {
        "janvier": "01", "février": "02", "mars": "03", "avril": "04",
        "mai": "05", "juin": "06", "juillet": "07", "août": "08",
        "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
    }
    current_year_month = None

    for line in lines:
        for mname, mnum in months_fr.items():
            if mname in line.lower():
                for y in range(2020, 2031):
                    if str(y) in line:
                        current_year_month = (str(y), mnum)
                        break

        if current_year_month and re.match(r"^\d{1,2}\s*:", line):
            parts = line.split(":", 1)
            if len(parts) == 2:
                day  = parts[0].strip().zfill(2)
                rest = parts[1].strip()
                year, month = current_year_month
                date_str = f"{year}-{month}-{day}"
                events.extend(parse_event_line(rest, date_str))

    return events


def parse_event_line(text, date_str):
    """Une ligne peut contenir plusieurs types d'événements séparés par un point."""
    event_keywords = {
        "Destruction":  [r"Destruction de\s+", r"Destruction d['']\s*"],
        "Dégradation":  [r"Dégradation de\s+", r"Dégradation d['']\s*"],
        "Ajout":        [r"Ajout des?\s+", r"Ajout et identification"],
        "Restauration": [r"Restauration de\s+", r"Restauration d['']\s*"],
        "Réactivation": [r"Réactivation de\s+", r"Réactivation d['']\s*"],
        "Alerte":       [r"Alerte à propos de\s+"],
    }
    results  = []
    segments = re.split(r"\.\s+(?=[A-ZÀÂÉ])", text)

    for segment in segments:
        etype = None
        for et, patterns in event_keywords.items():
            if any(re.search(p, segment, re.IGNORECASE) for p in patterns):
                etype = et
                break
        if not etype:
            continue
        invaders = re.findall(r'\b([A-Z]{1,6}_\d+)\b', segment)
        if not invaders:
            continue
        uid = hashlib.md5(
            f"{date_str}|{etype}|{'|'.join(sorted(invaders))}".encode()
        ).hexdigest()[:12]
        results.append({"date": date_str, "type": etype, "invaders": invaders, "id": uid})

    return results


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
    # Cherche le préfixe le plus long qui matche
    for city in sorted(CITY_NAMES.keys(), key=len, reverse=True):
        if code.startswith(city):
            return CITY_NAMES[city]
    return code


def format_message(event, invaders):
    emoji = EMOJIS.get(event["type"], "📍")
    lines = [f"{emoji} <b>{event['type']}</b>  —  {event['date']}"]

    # Groupe par ville
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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Vérification des news…")

    seen_ids   = load_seen_ids()
    events     = fetch_news()
    new_events = [e for e in events if e["id"] not in seen_ids and should_notify(e)]

    print(f"  {len(events)} événements trouvés, {len(new_events)} nouveaux.")

    if not new_events:
        print("  Rien de nouveau !")
        return

    for event in new_events:
        invaders = filter_invaders(event)
        send_telegram(format_message(event, invaders))
        seen_ids.add(event["id"])
        print(f"  ✓ {event['type']} — {invaders}")

    save_seen_ids(seen_ids)
    print(f"  {len(new_events)} notification(s) envoyée(s).")


if __name__ == "__main__":
    main()
