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
GRAPH_URL = "https://graph.facebook.com/v21.0"  # version stable
MAX_CHARS = 4800
MAX_POSTS = 8
MAX_SUMMARIES = 180
UNNAMED = "Autres compétitions"
STATE_FILE = "state.json"
MIN_INTERVAL_SECONDS = 4 * 60  # 4 minutes minimum entre deux posts normaux

# Championnats prioritaires (toujours en haut)
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
    ("🟥", "redCards", False),
    ("🚫", "foulsCommitted", True),
    ("🏹", "totalShots", True),
    ("🎯", "shotsOnTarget", True),
    ("🅿️", "possessionPct", True),
    ("🧤", "saves", False),
]

TEMPLATES = ["dates={d}&limit=1000", "dates={d}", ""]
QUERY = {}
errors = 0


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ScoreZone/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def publish(message):
    global errors
    if DRY_RUN:
        print("[DRY_RUN]\n" + message + "\n" + "=" * 50)
        return True
    data = urllib.parse.urlencode({"message": message, "access_token": PAGE_TOKEN}).encode()
    req = urllib.request.Request(f"{GRAPH_URL}/{PAGE_ID}/feed", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30):
            print(f"✅ Publié ({len(message)} car.)")
            return True
    except urllib.error.HTTPError as e:
        print("❌ Erreur Facebook :", e.read().decode()[:300])
    except Exception as e:
        print("❌ Erreur :", e)
    errors += 1
    return False


def fetch_scoreboard(slug):
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
            if kind not in QUERY:
                QUERY[kind] = tpl
            return {"events": events, "leagues": leagues}
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 400:
                continue
            raise
    raise last


def is_live(ev):
    return (ev.get("status") or {}).get("type", {}).get("state") == "in"


def flag_for(slug):
    return FLAGS.get((slug or "").split(".")[0], "🌍")


def league_name(ev, names):
    lg = ev.get("league")
    if isinstance(lg, dict) and lg.get("name"):
        return lg["name"]
    for part in (ev.get("uid") or "").split("\~"):
        if part.startswith("l:") and names.get(part[2:]):
            return names[part[2:]]
    return UNNAMED


def make_group(name, tier_if_named=1):
    return (2 if name == UNNAMED else tier_if_named, 0, name)


def collect():
    found = {}
    for i, (slug, flag, name) in enumerate(PRIORITY):
        try:
            data = fetch_scoreboard(slug)
        except Exception as e:
            print(f"{slug} : {e}")
            continue
        for ev in data["events"]:
            if is_live(ev) and ev["id"] not in found:
                found[ev["id"]] = {
                    "ev": ev, "group": (0, i, name), "flag": flag,
                    "name": name, "slug": slug, "priority": True,
                }
    n_priority = len(found)
    try:
        data = fetch_scoreboard("all")
        names = {str(lg.get("id")): lg.get("name") for lg in data["leagues"]}
        for ev in data["events"]:
            if is_live(ev) and ev["id"] not in found:
                name = league_name(ev, names)
                found[ev["id"]] = {
                    "ev": ev, "group": make_group(name), "flag": "🌍",
                    "name": name, "slug": None, "priority": False,
                }
    except Exception as e:
        print(f"all : {e}")
    print(f"{n_priority} prioritaire(s) + {len(found) - n_priority} autre(s) en direct")
    return list(found.values())


def fetch_details(items):
    stats, extra = {}, {}
    for i, it in enumerate(items):
        if i >= MAX_SUMMARIES:
            break
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
                ls[c.get("homeAway")] = [int(float(x.get("value", 0))) for x in c.get("linescores", [])]
            info["ls"] = ls
        except (ValueError, TypeError):
            pass
        extra[eid] = info
        time.sleep(0.12)
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
    return sum(1 for d in comp.get("details", []) if d.get(flag) and (d.get("team") or {}).get("id") == team_id)


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
        f"◉ {clock_label(ev)} | {home['team']['displayName']} {home.get('score', 0)}-{away.get('score', 0)} {away['team']['displayName']}"
    ]

    hl, al = half_scores(home, away, item)
    try:
        consistent = bool(hl and al) and sum(hl) == int(float(home.get("score", 0))) and sum(al) == int(float(away.get("score", 0)))
    except (ValueError, TypeError):
        consistent = False
    if consistent and name != "STATUS_FIRST_HALF":
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
    else:
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
        # Légende (comme dans les vidéos)
        legend = (
            "\n────────────────────\n"
            "⛳ Corners  🟨 Cartons jaunes  🟥 Cartons rouges\n"
            "🚫 Fautes  🏹 Tirs  🎯 Tirs cadrés  🅿️ Possession  🧤 Arrêts"
        )
        posts.append(cur.rstrip() + legend)
    return posts


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_post": 0, "matches": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_post": 0, "matches": {}}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def detect_important_change(items, old_state):
    """Retourne True s'il y a un but ou un carton rouge dans un match prioritaire."""
    old = old_state.get("matches", {})
    for it in items:
        if not it["priority"]:
            continue
        ev = it["ev"]
        eid = ev["id"]
        comp = ev["competitions"][0]
        home = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
        away = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
        score_h = int(float(home.get("score", 0)))
        score_a = int(float(away.get("score", 0)))
        red_h = card_counts(comp, home["team"]["id"], "redCard")
        red_a = card_counts(comp, away["team"]["id"], "redCard")

        prev = old.get(eid, {})
        if (score_h > prev.get("sh", 0) or score_a > prev.get("sa", 0) or
            red_h > prev.get("rh", 0) or red_a > prev.get("ra", 0)):
            print(f"🔥 Changement important détecté : {home['team']['displayName']} {score_h}-{score_a} {away['team']['displayName']}")
            return True
    return False


def update_state(items, old_state):
    new_matches = {}
    for it in items:
        ev = it["ev"]
        eid = ev["id"]
        comp = ev["competitions"][0]
        home = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
        away = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
        new_matches[eid] = {
            "sh": int(float(home.get("score", 0))),
            "sa": int(float(away.get("score", 0))),
            "rh": card_counts(comp, home["team"]["id"], "redCard"),
            "ra": card_counts(comp, away["team"]["id"], "redCard"),
        }
    return {
        "last_post": int(time.time()),
        "matches": new_matches,
    }


def main():
    if TEST_POST:
        ok = publish("✅ Test ScoreZone : le bot fonctionne correctement.")
        sys.exit(0 if ok else 1)

    items = collect()
    if not items:
        print("Aucun match en direct.")
        return

    items.sort(key=lambda it: it["group"])
    stats, extra = fetch_details(items)
    enrich(items, extra)

    state = load_state()
    now = int(time.time())
    force = detect_important_change(items, state)
    elapsed = now - state.get("last_post", 0)

    if force or elapsed >= MIN_INTERVAL_SECONDS or state.get("last_post", 0) == 0:
        posts = build_posts(items, stats)[:MAX_POSTS]
        success = True
        for post in posts:
            if not publish(post):
                success = False
        if success:
            new_state = update_state(items, state)
            save_state(new_state)
            print(f"État sauvegardé (force={force}, elapsed={elapsed}s)")
    else:
        print(f"⏳ Trop tôt ({elapsed}s < {MIN_INTERVAL_SECONDS}s) et aucun changement important → pas de publication")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
