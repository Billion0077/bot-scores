import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_KEY = os.environ["APIFOOTBALL_KEY"]
PAGE_ID = os.environ["FB_PAGE_ID"]
PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
TEST_POST = os.environ.get("TEST_POST", "false").lower() == "true"

# Rythme prevu des executions (sert a repartir les 100 requetes gratuites)
INTERVAL_MIN = int(os.environ.get("INTERVAL_MIN", "30"))
END_HOUR = int(os.environ.get("END_HOUR", "23"))  # heure UTC de fin

API_URL = "https://v3.football.api-sports.io"
GRAPH_URL = "https://graph.facebook.com/v27.0"
MAX_CHARS = 5000  # taille max d'un post
MAX_POSTS = 4  # nombre max de posts par execution

# Compétitions affichées en premier :
# LDC, Europa, Conférence, Premier League, Liga, Serie A, Bundesliga, Ligue 1
PRIORITY = {2, 3, 848, 39, 140, 135, 78, 61}
LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "SUSP", "INT"}

STATS = [
    ("⛳", "Corner Kicks", True),
    ("🟨", "Yellow Cards", True),
    ("🟥", "Red Cards", False),  # affiche seulement s'il y en a
    ("SUBS", None, True),
    ("🚫", "Fouls", True),
    ("🏹", "Total Shots", True),
    ("🎯", "Shots on Goal", True),
    ("🅿️", "Ball Possession", True),
]

errors = 0
remaining = None


def n(x):
    return 0 if x is None else x


def api_get(path):
    global remaining
    req = urllib.request.Request(API_URL + path, headers={"x-apisports-key": API_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        remaining = resp.headers.get("x-ratelimit-requests-remaining")
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError(f"Erreur API-Football : {data['errors']}")
    return data.get("response", [])


def publish(message):
    """Publie sur la page Facebook. Renvoie True si c'est reussi."""
    global errors
    if DRY_RUN:
        print("[TEST]\n" + message + "\n")
        return True
    data = urllib.parse.urlencode(
        {"message": message, "access_token": PAGE_TOKEN}
    ).encode()
    req = urllib.request.Request(f"{GRAPH_URL}/{PAGE_ID}/feed", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30):
            print(f"Publié ({len(message)} caractères)")
            return True
    except urllib.error.HTTPError as e:
        print("Erreur Facebook :", e.read().decode())
    except Exception as e:
        print("Erreur :", e)
    errors += 1
    return False


def flag(m):
    url = m["league"].get("flag") or ""
    code = url.rsplit("/", 1)[-1].split(".")[0].lower()
    if len(code) == 2 and code.isalpha():
        return "".join(chr(0x1F1E6 + ord(c) - 97) for c in code)
    return "🌍"


def sort_key(m):
    lg = m["league"]
    return (
        0 if lg.get("id") in PRIORITY else 1,
        lg.get("country") or "",
        lg["name"],
        -(m["fixture"]["status"].get("elapsed") or 0),
    )


def status_label(m):
    st = m["fixture"]["status"]
    s = st["short"]
    if s == "HT":
        return "MT"
    if s == "BT":
        return "Pause"
    if s == "P":
        return "TAB"
    if s in ("SUSP", "INT"):
        return "Interr."
    el = st.get("elapsed") or 0
    extra = st.get("extra")
    return f"{el}+{extra}'" if extra else f"{el}'"


def stat_value(stats, team_id, name):
    for t in stats or []:
        if t["team"]["id"] == team_id:
            for s in t["statistics"]:
                if s["type"] == name:
                    return s["value"]
    return None


def subs_count(m, team_id):
    return sum(
        1
        for e in m.get("events") or []
        if e["type"] == "subst" and e["team"]["id"] == team_id
    )


def match_block(m, stats_by_id):
    t = m["teams"]
    g = m["goals"]
    short = m["fixture"]["status"]["short"]
    lines = [
        f"◉ {status_label(m)} | {t['home']['name']} {n(g['home'])}-{n(g['away'])} "
        f"{t['away']['name']}"
    ]

    ht = (m.get("score") or {}).get("halftime") or {}
    if ht.get("home") is not None and short != "1H":
        half = f"➡ 1re MT : {ht['home']}-{ht['away']}"
        sh = n(g["home"]) - ht["home"]
        sa = n(g["away"]) - ht["away"]
        if short != "HT" and sh >= 0 and sa >= 0:
            half += f" | 2e MT : {sh}-{sa}"
        lines.append("   " + half)

    stats = stats_by_id.get(m["fixture"]["id"])
    if stats:
        hid, aid = t["home"]["id"], t["away"]["id"]
        parts = []
        for emoji, name, always in STATS:
            if name is None:  # remplacements
                h, a = subs_count(m, hid), subs_count(m, aid)
                parts.append(f"🔄{h}-{a}")
                continue
            h = stat_value(stats, hid, name)
            a = stat_value(stats, aid, name)
            if h is None and a is None:
                continue
            if not always and n(h) == 0 and n(a) == 0:
                continue
            if name == "Ball Possession":
                parts.append(f"{emoji}{h}-{a}")
            else:
                parts.append(f"{emoji}{n(h)}-{n(a)}")
        if parts:
            lines.append("   " + " ".join(parts))
    return "\n".join(lines)


def stats_budget():
    """Nombre d'appels 'statistiques' permis pour cette execution."""
    now = datetime.datetime.now(datetime.timezone.utc)
    minutes_left = END_HOUR * 60 - (now.hour * 60 + now.minute)
    runs_left = max(1, minutes_left // INTERVAL_MIN + 1)
    try:
        rem = int(remaining)
    except (TypeError, ValueError):
        return 1
    return max(0, (rem - 2) // runs_left)


def fetch_stats(matches, budget):
    out = {}
    ids = [str(m["fixture"]["id"]) for m in matches]
    for i in range(0, len(ids), 20):
        if budget <= 0:
            break
        budget -= 1
        for f in api_get("/fixtures?ids=" + "-".join(ids[i : i + 20])):
            out[f["fixture"]["id"]] = f.get("statistics") or []
    return out


def build_posts(matches, stats):
    now = datetime.datetime.now(datetime.timezone.utc)
    header = f"⚽🚩 LIVE SCORE ➤ {now:%H:%M} - GMT\n"
    posts, cur, last = [], header, None
    for m in matches:
        country = m["league"].get("country") or "Monde"
        key = (country, m["league"]["name"])
        title = f"\n{flag(m)} {country} ➤ {m['league']['name']}\n"
        block = match_block(m, stats) + "\n"
        add = (title if key != last else "") + block
        if len(cur) + len(add) > MAX_CHARS and cur != header:
            posts.append(cur.rstrip())
            cur = header + title + block
        else:
            cur += add
        last = key
    if cur != header:
        posts.append(cur.rstrip())
    return posts


def main():
    if TEST_POST:
        ok = publish("✅ Test : le bot de scores fonctionne.")
        sys.exit(0 if ok else 1)

    live = [
        m
        for m in api_get("/fixtures?live=all")
        if m["fixture"]["status"]["short"] in LIVE
    ]
    print(f"{len(live)} match(s) en direct. Requêtes restantes : {remaining}")
    if not live:
        return
    live.sort(key=sort_key)

    stats = fetch_stats(live, stats_budget())
    print(f"Statistiques récupérées pour {len(stats)} match(s). Restantes : {remaining}")

    for post in build_posts(live, stats)[:MAX_POSTS]:
        publish(post)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
    
