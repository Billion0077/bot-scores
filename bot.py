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
MAX_POSTS = 10  # nombre max de posts par execution
MAX_SUMMARIES = 300  # nombre max de matchs dont on lit les statistiques
UNNAMED = "Autres compétitions"

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

# Drapeaux selon le debut du code de la competition (ex. "ger.2" -> Allemagne)
FLAGS = {
    "eng": "🇬🇧", "sco": "🇬🇧", "wal": "🇬🇧", "nir": "🇬🇧", "esp": "🇪🇸", "ita": "🇮🇹",
    "ger": "🇩🇪", "fra": "🇫🇷", "ned": "🇳🇱", "por": "🇵🇹", "tur": "🇹🇷", "rus": "🇷🇺",
    "chn": "🇨🇳", "ksa": "🇸🇦", "bra": "🇧🇷", "arg": "🇦🇷", "usa": "🇺🇸", "mex": "🇲🇽",
    "bel": "🇧🇪", "gre": "🇬🇷", "swe": "🇸🇪", "nor": "🇳🇴", "den": "🇩🇰", "sui": "🇨🇭",
    "aut": "🇦🇹", "cze": "🇨🇿", "pol": "🇵🇱", "ukr": "🇺🇦", "jpn": "🇯🇵", "kor": "🇰🇷",
    "aus": "🇦🇺", "col": "🇨🇴", "chi": "🇨🇱", "uru": "🇺🇾", "ecu": "🇪🇨", "par": "🇵🇾",
    "per": "🇵🇪", "ven": "🇻🇪", "bol": "🇧🇴", "egy": "🇪🇬", "mar": "🇲🇦", "alg": "🇩🇿",
    "tun": "🇹🇳", "rsa": "🇿🇦", "irn": "🇮🇷", "qat": "🇶🇦", "uae": "🇦🇪", "isr": "🇮🇱",
    "cro": "🇭🇷", "srb": "🇷🇸", "rou": "🇷🇴", "hun": "🇭🇺", "bul": "🇧🇬", "svk": "🇸🇰",
    "svn": "🇸🇮", "fin": "🇫🇮", "irl": "🇮🇪", "ind": "🇮🇳", "tha": "🇹🇭", "idn": "🇮🇩",
    "vie": "🇻🇳", "cyp": "🇨🇾", "alb": "🇦🇱", "geo": "🇬🇪", "arm": "🇦🇲", "aze": "🇦🇿",
    "kaz": "🇰🇿", "blr": "🇧🇾", "lva": "🇱🇻", "ltu": "🇱🇹", "est": "🇪🇪", "isl": "🇮🇸",
    "mlt": "🇲🇹", "lux": "🇱🇺", "bih": "🇧🇦", "mne": "🇲🇪", "mkd": "🇲🇰", "mda": "🇲🇩",
    "gua": "🇬🇹", "crc": "🇨🇷", "hon": "🇭🇳", "slv": "🇸🇻", "pan": "🇵🇦", "jam": "🇯🇲",
    "can": "🇨🇦", "nzl": "🇳🇿", "gha": "🇬🇭", "nga": "🇳🇬", "ken": "🇰🇪", "sen": "🇸🇳",
}

STATS = [
    ("⛳", "wonCorners", True),
    ("🟨", "yellowCards", True),
    ("🟥", "redCards", False),  # affiche seulement s'il y en a
    ("🚫", "foulsCommitted", True),
    ("🏹", "totalShots", True),
    ("🎯", "shotsOnTarget", True),
    ("🅿️", "possessionPct", True),
]

TEMPLATES = ["dates={d}&limit=1000", "dates={d}", ""]  # essayes dans cet ordre
QUERY = {}  # format retenu apres le premier succes
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


def fetch_scoreboard(slug):
    """Matchs d'hier et d'aujourd'hui (UTC). Essaie plusieurs formats si ESPN refuse."""
    kind = "all" if slug == "all" else "league"
    templates = [QUERY[kind]] if kind in QUERY else TEMPLATES
    today = datetime.datetime.now(datetime.timezone.utc).date()
    days = [today - datetime.timedelta(days=1), today]
    last = None
    for tpl in templates:
        try:
            events, leagues, seen = [], [], set()
            for d in days if tpl else [None]:
                q = tpl.replace("{d}", f"{d:%Y%m%d}") if d else tpl
                data = get(f"{BASE}/{slug}/scoreboard" + (f"?{q}" if q else ""))
                leagues += data.get("leagues", [])
                for ev in data.get("events", []):
                    if ev["id"] not in seen:
                        seen.add(ev["id"])
                        events.append(ev)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 400:
                continue
            raise
        if kind not in QUERY:
            QUERY[kind] = tpl
            print(f"Format ESPN retenu ({kind}) : {tpl or 'aucun'}")
        return {"events": events, "leagues": leagues}
    raise last


def is_live(ev):
    return (ev.get("status") or {}).get("type", {}).get("state") == "in"


def flag_for(slug):
    return FLAGS.get((slug or "").split(".")[0], "🌍")


def league_name(ev, names):
    lg = ev.get("league")
    if isinstance(lg, dict) and lg.get("name"):
        return lg["name"]
    for part in (ev.get("uid") or "").split("~"):
        if part.startswith("l:") and names.get(part[2:]):
            return names[part[2:]]
    return UNNAMED


def make_group(name, tier_if_named=1):
    return (2 if name == UNNAMED else tier_if_named, 0, name)


def collect():
    """Renvoie la liste des matchs en direct (competitions principales d'abord)."""
    found = {}
    for i, (slug, flag, name) in enumerate(PRIORITY):
        try:
            data = fetch_scoreboard(slug)
        except Exception as e:
            print(f"{slug} : erreur {e}")
            continue
        for ev in data["events"]:
            if is_live(ev) and ev["id"] not in found:
                found[ev["id"]] = {
                    "ev": ev, "group": (0, i, name), "flag": flag, "name": name,
                    "slug": slug, "priority": True,
                }
    n_priority = len(found)
    try:
        data = fetch_scoreboard("all")
        names = {str(lg.get("id")): lg.get("name") for lg in data["leagues"]}
        for ev in data["events"]:
            if is_live(ev) and ev["id"] not in found:
                name = league_name(ev, names)
                found[ev["id"]] = {
                    "ev": ev, "group": make_group(name), "flag": "🌍", "name": name,
                    "slug": None, "priority": False,
                }
    except Exception as e:
        print(f"all : erreur {e}")
    print(f"{n_priority} match(s) en direct dans les compétitions principales, "
          f"{len(found) - n_priority} autre(s).")
    return list(found.values())


def fetch_details(items):
    """Lit statistiques, mi-temps et nom de competition de chaque match."""
    stats, extra = {}, {}
    calls = 0
    for it in items:
        if calls >= MAX_SUMMARIES:
            break
        calls += 1
        eid = it["ev"]["id"]
        try:
            data = get(f"{BASE}/{it['slug'] or 'all'}/summary?event={eid}")
        except Exception:
            continue
        teams = {}
        for t in (data.get("boxscore") or {}).get("teams", []):
            tid = (t.get("team") or {}).get("id")
            teams[tid] = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
        if teams:
            stats[eid] = teams
        info = {}
        header = data.get("header") or {}
        lg = header.get("league") or {}
        if lg.get("name"):
            info["league"] = lg["name"]
        info["slug"] = lg.get("slug")
        try:
            comps = (header.get("competitions") or [{}])[0].get("competitors", [])
            ls = {}
            for c in comps:
                ls[c.get("homeAway")] = [
                    int(float(x.get("value", 0))) for x in c.get("linescores", [])
                ]
            info["ls"] = ls
        except (ValueError, TypeError):
            pass
        extra[eid] = info
        time.sleep(0.15)
    print(f"Détails lus pour {len(extra)} match(s) sur {calls} essayé(s), "
          f"statistiques pour {len(stats)}.")
    return stats, extra


def enrich(items, extra):
    for it in items:
        info = extra.get(it["ev"]["id"]) or {}
        it["ls"] = info.get("ls")
        if not it["priority"]:
            if info.get("league"):
                it["name"] = info["league"]
                it["group"] = make_group(it["name"])
            it["flag"] = flag_for(info.get("slug"))
    items.sort(key=lambda it: it["group"])


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


def half_scores(home, away, item):
    try:
        hl = [int(float(x.get("value", 0))) for x in home.get("linescores", [])]
        al = [int(float(x.get("value", 0))) for x in away.get("linescores", [])]
    except (ValueError, TypeError):
        hl, al = [], []
    if not (hl and al) and item.get("ls"):
        hl = item["ls"].get("home") or []
        al = item["ls"].get("away") or []
    return hl, al


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

    hl, al = half_scores(home, away, item)
    if hl and al and name != "STATUS_FIRST_HALF":
        half = f"➡ 1re MT : {hl[0]}-{al[0]}"
        if name != "STATUS_HALFTIME" and len(hl) > 1 and len(al) > 1:
            half += f" | 2e MT : {hl[1]}-{al[1]}"
        lines.append("   " + half)

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
    items.sort(key=lambda it: it["group"])
    stats, extra = fetch_details(items)
    enrich(items, extra)
    for post in build_posts(items, stats)[:MAX_POSTS]:
        publish(post)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
    
