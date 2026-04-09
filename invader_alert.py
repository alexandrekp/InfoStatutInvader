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

# Préfixes des villes françaises — on vérifie avec startswith
WATCHED_CITIES = [
    "PA",    # Paris (PA01, PA02, PA05, PA18, PA19, PA20, PA92, PA93, PA94, PA95...)
    "MARS",  # Marseille
    "GRN",   # Grenoble
    "LY",    # Lyon
    "TLS",   # Toulouse
    "LIL",   # Lille
    "AVI",   # Avignon
    "NIM",   # Nîmes
    "BAB",   # Bayonne-Biarritz
    "MPL",   # Montpellier
    "ORLN",  # Orléans
    "AMI",   # Amiens
    "CAZ",   # Cazaux
    "LCT",   # La Ciotat
    "CAPF",  # Cap Ferret
    "PAU",   # Pau
]

CITY_NAMES = {
    "PA":   "Paris",
    "MARS": "Marseille",
    "GRN":  "Grenoble",
    "LY":   "Lyon",
    "TLS":  "Toulouse",
    "LIL":  "Lille",
    "AVI":  "Avignon",
    "NIM":  "Nîmes",
    "BAB":  "Bayonne-Biarritz",
    "MPL":  "Montpellier",
    "ORLN": "Orléans",
    "AMI":  "Amiens",
    "CAZ":  "Cazaux",
    "LCT":  "La Ciotat",
    "CAPF": "Cap Ferret",
    "PAU":  "Pau",
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
    html = resp.text
    return parse_html(html)


def parse_html(html):
    """
    Parse directement le HTML brut.
    Les invaders sont dans des appels: lienm("PA05",213) -> code PA05_213
    Les blocs de news: <b>07 :</b> texte...
    Les mois: <b>XX :</b> ... précédé du nom du mois + année
    """
    events = []

    # Extrait tous les blocs mois avec leur position dans le HTML
    # Format: "avril 2026" ou "mars 2026"
    month_re = re.compile(
        r'(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})',
        re.IGNORECASE
    )

    # Extrait les blocs jour: <b>07 :</b> ... jusqu'au prochain <b>
    # On travaille sur le HTML brut
    day_block_re = re.compile(
        r'<b>(\d{1,2})\s*:</b>(.*?)(?=<b>\d{1,2}\s*:|(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}|$)',
        re.DOTALL | re.IGNORECASE
    )

    # Extrait les codes invader: lienm("PA05",213) -> PA05_213
    invader_re = re.compile(r'lienm\("([^"]+)",\s*(\d+)\)')

    # Trouve toutes les positions des mois dans le HTML
    month_positions = []
    for m in month_re.finditer(html):
        mname = m.group(1).lower()
        year  = m.group(2)
        mnum  = MONTHS_FR.get(mname, "01")
        month_positions.append((m.start(), year, mnum))

    print(f"  Mois trouvés: {len(month_positions)}")

    # Pour chaque bloc jour, détermine le mois/année en fonction de sa position
    for day_match in day_block_re.finditer(html):
        day       = day_match.group(1).zfill(2)
        block_html = day_match.group(2)
        pos       = day_match.start()

        # Trouve le mois le plus proche AVANT ce bloc
        year, mnum = "2026", "01"
        for mpos, my, mm in month_positions:
            if mpos <= pos:
                year, mnum = my, mm
            else:
                break

        date_str = f"{year}-{mnum}-{day}"

        # Extrait les invaders du bloc
        invaders = [f"{code}_{num}" for code, num in invader_re.findall(block_html)]
        if not invaders:
            continue

        # Extrait le texte du bloc pour détecter le type
        block_text = re.sub(r'<[^>]+>', ' ', block_html)
        block_text = re.sub(r'\s+', ' ', block_text).strip()

        # Découpe en segments par point
        segments = re.split(r'\.\s+(?=[A-ZÀÂÉ])', block_text)

        event_keywords = {
            "Destruction":  r"Destruction",
            "Dégradation":  r"Dégradation",
            "Ajout":        r"Ajout",
            "Restauration": r"Restauration",
            "Réactivation": r"Réactivation",
            "Alerte":       r"Alerte",
        }

        # Associe chaque invader au bon type d'événement
        used_invaders = set()
        for segment in segments:
            etype = None
            for et, pattern in event_keywords.items():
                if re.search(pattern, segment, re.IGNORECASE):
                    etype = et
                    break
            if not etype:
                continue

            # Invaders mentionnés dans ce segment
            seg_invaders = [f"{c}_{n}" for c, n in invader_re.findall(
                block_html[block_html.find(segment[:20]) if segment[:20] in block_html else 0:]
            )]
            # Fallback: prend tous les invaders non encore utilisés
            seg_invaders = [i for i in invaders if i not in used_invaders]
            if not seg_invaders:
                continue

            used_invaders.update(seg_invaders)
            uid = hashlib.md5(
                f"{date_str}|{etype}|{'|'.join(sorted(seg_invaders))}".encode()
            ).hexdigest()[:12]
            events.append({
                "date": date_str,
                "type": etype,
                "invaders": seg_invaders,
                "id": uid,
            })

    print(f"  {len(events)} événements trouvés au total")
    return events


# ── Filtrage ─────────────────────────────────────────────────────────────────
def get_city_prefix(invader_code):
    """
    Extrait le préfixe ville d'un code comme PA05_213 -> PA
    ou MARS_39 -> MARS
    On cherche le préfixe alpha avant les chiffres ou le underscore.
    """
    m = re.match(r'^([A-Z]+)', invader_code)
    if not m:
        return ""
    alpha = m.group(1)
    # Retire les chiffres de fin s'il y en a (ex: PA05 -> PA)
    return re.sub(r'\d+$', '', alpha)


def filter_invaders(event):
    result = []
    for inv in event["invaders"]:
        prefix = get_city_prefix(inv)
        if any(prefix == city or prefix.startswith(city) for city in WATCHED_CITIES):
            result.append(inv)
    return result


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
    prefix = get_city_prefix(invader_code)
    for city in sorted(CITY_NAMES.keys(), key=len, reverse=True):
        if prefix == city or prefix.startswith(city):
            return CITY_NAMES[city]
    return prefix

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

    events   = fetch_news()

    # Debug
    for e in events:
        prefix = get_city_prefix(e['invaders'][0]) if e['invaders'] else '?'
        print(f"  EVENT: {e['type']} {e['invaders']} {e['date']} (prefix={prefix})")

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

    if now.hour == 8:
        print("  Envoi du résumé quotidien…")
        send_telegram(format_daily_summary(stats))

if __name__ == "__main__":
    main()
