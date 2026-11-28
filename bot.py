import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PAGE_ID = os.environ["FB_PAGE_ID"]
PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
TEST_POST = os.environ.get("TEST_POST", "false").lower() == "true"

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
GRAPH_URL = "https://graph.facebook.com/v27.0"
MAX_CHARS = 5000  # taille max d'un post
MAX_POSTS = 4  # nombre max de posts par execution
MAX_SUMMARIES = 60  # nombre max de matchs dont on lit les statistiques

# Competitions affichees en premier : (code ESPN, drapeau, nom)
PRIORITY = [
    ("uefa.champions", "🇪🇺", "UEFA Champions League"),
    ("uefa.europa", "🇪🇺", "UEFA Europa League"),
    ("uefa.europa.conf", "🇪🇺", "UEFA Conference League"),
    ("eng.1", "🇬🇧", "Premier League"),
    ("esp.1", "🇪🇸", "LaLiga"),
    ("ita.1", "🇮🇹", "Serie A"),
    ("ger.1", "🇩🇪", "Bundesliga"),
    ("fra.1", "🇫🇷", "Ligue 1"),
]

STATS = [
    ("⛳", "wonCorners", True),
    ("🟨", "yellowCards", True),
    ("🟥", "redCards", False),  # affiche seulement s'il y en a
    ("🚫", "foulsCommitted", True),
    ("🏹", "totalShots", True),
    ("🎯", "shotsOnTarget", True),
    ("🅿️", "possessionPct", True),
]

errors = 0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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


def date_range():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    yesterday = today - datetime.timedelta(days=1)
    return f"{yesterday:%Y%m%d}-{today:%Y%m%d}"


def fetch_scoreboard(slug):
    return get(f"{BASE}/{slug}/scoreboard?dates={date_range()}&limit=1000")


def is_live(ev):
    return (ev.get("status") or {}).get("type", {}).get("state") == "in"


def league_name(ev, names):
    lg = ev.get("league")
    if isinstance(lg, dict) and lg.get("name"):
        return lg["name"]
    for part in (ev.get("uid") or "").split("~"):
        if part.startswith("l:") and names.get(part[2:]):
            return names[part[2:]]
    return "Autres compétitions"


def collect():
    """Renvoie la liste des matchs en direct (competitions principales d'abord)."""
    found = {}
    for i, (slug, flag, name) in enumerate(PRIORITY):
        try:
            data = fetch_scoreboard(slug)
        except Exception as e:
            print(f"{slug} : erreur {e}")
            continue
        for ev in data.get("events", []):
            if is_live(ev) and ev["id"] not in found:
                found[ev["id"]] = {
                    "ev": ev, "group": (0, i, name), "flag": flag, "name": name, "slug": slug,
                }
    n_priority = len(found)
    try:
        data = fetch_scoreboard("all")
        names = {str(lg.get("id")): lg.get("name") for lg in data.get("leagues", [])}
        for ev in data.get("events", []):
            if is_live(ev) and ev["id"] not in found:
                name = league_name(ev, names)
                found[ev["id"]] = {
                    "ev": ev, "group": (1, 0, name), "flag": "🌍", "name": name, "slug": None,
                }
    except Exception as e:
        print(f"all : erreur {e}")
    print(f"{n_priority} match(s) en direct dans les compétitions principales, "
          f"{len(found) - n_priority} autre(s).")
    return sorted(found.values(), key=lambda it: it["group"])


def fetch_stats(items):
    out = {}
    calls = 0
    for it in items:
        if calls >= MAX_SUMMARIES:
            break
        calls += 1
        slug = it["slug"] or "all"
        try:
            data = get(f"{BASE}/{slug}/summary?event={it['ev']['id']}")
        except Exception:
            continue
        teams = {}
        for t in (data.get("boxscore") or {}).get("teams", []):
            tid = (t.get("team") or {}).get("id")
            teams[tid] = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
        if teams:
            out[it["ev"]["id"]] = teams
        time.sleep(0.15)
    print(f"Statistiques lues pour {len(out)} match(s) sur {calls} essayé(s).")
    return out


def clock_label(ev):
    st = ev["status"]
    name = st["type"].get("name", "")
    if name == "STATUS_HALFTIME":
        return "MT"
    if name == "STATUS_SHOOTOUT":
        return "TAB"
    return st.get("displayClock") or st["type"].get("shortDetail") or "?"


def fmt(name, value):
    if value is None:
        return None
    if name == "possessionPct":
        try:
            return f"{round(float(value))}%"
        except ValueError:
            return None
    return value


def card_counts(comp, team_id, flag):
    return sum(
        1
        for d in comp.get("details", [])
        if d.get(flag) and (d.get("team") or {}).get("id") == team_id
    )


def match_block(item, stats):
    ev = item["ev"]
    comp = ev["competitions"][0]
    home = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
    away = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
    hid, aid = home["team"]["id"], away["team"]["id"]
    name = ev["status"]["type"].get("name", "")
    lines = [
        f"◉ {clock_label(ev)} | {home['team']['displayName']} {home.get('score', 0)}-"
        f"{away.get('score', 0)} {away['team']['displayName']}"
    ]

    try:
        hl = [int(float(x.get("value", 0))) for x in home.get("linescores", [])]
        al = [int(float(x.get("value", 0))) for x in away.get("linescores", [])]
        if hl and al and name != "STATUS_FIRST_HALF":
            half = f"➡ 1re MT : {hl[0]}-{al[0]}"
            if name != "STATUS_HALFTIME" and len(hl) > 1 and len(al) > 1:
                half += f" | 2e MT : {hl[1]}-{al[1]}"
            lines.append("   " + half)
    except (ValueError, TypeError):
        pass

    st = stats.get(ev["id"])
    parts = []
    if st:
        for emoji, key, always in STATS:
            h = fmt(key, (st.get(hid) or {}).get(key))
            a = fmt(key, (st.get(aid) or {}).get(key))
            if h is None and a is None:
                continue
            h, a = h or "0", a or "0"
            if not always and h == "0" and a == "0":
                continue
            parts.append(f"{emoji}{h}-{a}")
    else:  # pas de statistiques : on compte les cartons dans les evenements
        yh, ya = card_counts(comp, hid, "yellowCard"), card_counts(comp, aid, "yellowCard")
        rh, ra = card_counts(comp, hid, "redCard"), card_counts(comp, aid, "redCard")
        if yh or ya:
            parts.append(f"🟨{yh}-{ya}")
        if rh or ra:
            parts.append(f"🟥{rh}-{ra}")
    if parts:
        lines.append("   " + " ".join(parts))
    return "\n".join(lines)


def build_posts(items, stats):
    now = datetime.datetime.now(datetime.timezone.utc)
    header = f"⚽🚩 LIVE SCORE ➤ {now:%H:%M} - GMT\n"
    posts, cur, last = [], header, None
    for it in items:
        title = f"\n{it['flag']} {it['name']}\n"
        block = match_block(it, stats) + "\n"
        add = (title if it["name"] != last else "") + block
        if len(cur) + len(add) > MAX_CHARS and cur != header:
            posts.append(cur.rstrip())
            cur = header + title + block
        else:
            cur += add
        last = it["name"]
    if cur != header:
        posts.append(cur.rstrip())
    return posts


def main():
    if TEST_POST:
        ok = publish("✅ Test : le bot de scores fonctionne.")
        sys.exit(0 if ok else 1)

    items = collect()
    if not items:
        print("Aucun match en direct.")
        return
    stats = fetch_stats(items)
    for post in build_posts(items, stats)[:MAX_POSTS]:
        publish(post)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
                
