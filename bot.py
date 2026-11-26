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

# 2 Ligue des champions, 3 Europa League, 848 Conference League,
# 39 Premier League, 140 Liga, 135 Serie A, 78 Bundesliga, 61 Ligue 1
LEAGUES = "2-3-848-39-140-135-78-61"
API_URL = "https://v3.football.api-sports.io"
GRAPH_URL = "https://graph.facebook.com/v27.0"
STATE_FILE = "state_v2.json"
MIN_REMAINING = 5  # petite reserve de requetes gratuites

LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "SUSP", "INT"}
DONE = {"FT", "AET", "PEN"}
CANCELLED = {"PST", "CANC", "ABD", "AWD", "WO"}

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


def quota_low():
    try:
        return remaining is not None and int(remaining) < MIN_REMAINING
    except ValueError:
        return False


def publish(message):
    """Publie sur la page Facebook. Renvoie True si c'est reussi."""
    global errors
    if DRY_RUN:
        print("[TEST] " + message.replace("\n", " | "))
        return True
    data = urllib.parse.urlencode(
        {"message": message, "access_token": PAGE_TOKEN}
    ).encode()
    req = urllib.request.Request(f"{GRAPH_URL}/{PAGE_ID}/feed", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30):
            print("Publie : " + message.replace("\n", " | "))
            return True
    except urllib.error.HTTPError as e:
        print("Erreur Facebook :", e.read().decode())
    except Exception as e:
        print("Erreur :", e)
    errors += 1
    return False


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def score_line(m):
    g = m["goals"]
    return (
        f"{m['teams']['home']['name']} {n(g['home'])} - "
        f"{n(g['away'])} {m['teams']['away']['name']}"
    )


def relevant(e):
    detail = (e.get("detail") or "").lower()
    if e["type"] == "Goal":
        return detail in ("normal goal", "penalty", "own goal")
    if e["type"] == "Card":
        return "red" in detail or "second yellow" in detail
    return False


def event_key(e):
    t = e["time"]
    pid = (e.get("player") or {}).get("id")
    return f"{e['type']}|{t.get('elapsed')}|{t.get('extra')}|{pid}|{e.get('detail')}"


def event_line(e):
    t = e["time"]
    minute = str(t.get("elapsed"))
    if t.get("extra"):
        minute += f"+{t['extra']}"
    minute += "'"
    player = (e.get("player") or {}).get("name") or "?"
    if e["type"] == "Goal":
        detail = e.get("detail")
        if detail == "Own Goal":
            return f"⚽ {minute} {player} (csc)"
        extra = " (pen.)" if detail == "Penalty" else ""
        assist = (e.get("assist") or {}).get("name")
        if assist:
            extra += f" (passe : {assist})"
        return f"⚽ {minute} {player}{extra}"
    return f"🟥 {minute} {player} ({e['team']['name']})"


def stat(m, team_id, name):
    for t in m.get("statistics") or []:
        if t["team"]["id"] == team_id:
            for s in t["statistics"]:
                if s["type"] == name:
                    return s["value"]
    return None


def pair(m, label, name):
    home = stat(m, m["teams"]["home"]["id"], name)
    away = stat(m, m["teams"]["away"]["id"], name)
    if home is None and away is None:
        return None
    return f"{label} : {n(home)} - {n(away)}"


def final_message(m):
    status = m["fixture"]["status"]["short"]
    text = f"🏁 TERMINÉ\n{score_line(m)}"
    if status == "AET":
        text += " (après prolongation)"
    if status == "PEN":
        p = m["score"]["penalty"]
        text += f"\nTirs au but : {n(p['home'])} - {n(p['away'])}"
    text += f"\n🏆 {m['league']['name']}"

    scorers = [
        event_line(e)
        for e in m.get("events") or []
        if e["type"] == "Goal" and relevant(e)
    ]
    if scorers:
        text += "\n\nButeurs :\n" + "\n".join(scorers)

    rows = [
        pair(m, "⛳ Corners", "Corner Kicks"),
        pair(m, "🚫 Fautes", "Fouls"),
        pair(m, "🎯 Tirs cadrés", "Shots on Goal"),
        pair(m, "🥅 Tirs", "Total Shots"),
        pair(m, "📈 Possession", "Ball Possession"),
        pair(m, "🟨 Cartons jaunes", "Yellow Cards"),
        pair(m, "🟥 Cartons rouges", "Red Cards"),
    ]
    rows = [r for r in rows if r]
    if rows:
        text += "\n\n📊 Statistiques :\n" + "\n".join(rows)
    return text


def process_live(m, state):
    fid = str(m["fixture"]["id"])
    s = state.setdefault(fid, {"kick": False, "ht": False, "posted": []})
    status = m["fixture"]["status"]["short"]
    elapsed = m["fixture"]["status"].get("elapsed") or 0
    comp = m["league"]["name"]
    line = score_line(m)

    if not s["kick"]:
        if status == "1H" and elapsed <= 15:
            title = f"{m['teams']['home']['name']} - {m['teams']['away']['name']}"
            if publish(f"🟢 COUP D'ENVOI\n{title}\n🏆 {comp}"):
                s["kick"] = True
        else:
            s["kick"] = True

    new = [
        e
        for e in m.get("events") or []
        if relevant(e) and event_key(e) not in s["posted"]
    ]
    if new:
        has_goal = any(e["type"] == "Goal" for e in new)
        head = "⚽ BUT !" if has_goal else "🟥 CARTON ROUGE"
        lines = "\n".join(event_line(e) for e in new)
        if publish(f"{head}\n{line} ({elapsed}')\n{lines}\n🏆 {comp}"):
            s["posted"] += [event_key(e) for e in new]

    if status == "HT" and not s["ht"]:
        if publish(f"⏸️ MI-TEMPS\n{line}\n🏆 {comp}"):
            s["ht"] = True


def miss(s):
    s["miss"] = s.get("miss", 0) + 1
    if s["miss"] >= 12:
        s["done"] = True


def process_finished(state, seen):
    pending = [fid for fid in state if fid not in seen and not state[fid].get("done")]
    if not pending:
        return
    if quota_low():
        print("Quota presque épuisé : statistiques reportées.")
        return
    for i in range(0, len(pending), 20):
        batch = pending[i : i + 20]
        found = set()
        for m in api_get("/fixtures?ids=" + "-".join(batch)):
            fid = str(m["fixture"]["id"])
            s = state.get(fid)
            if s is None:
                continue
            found.add(fid)
            status = m["fixture"]["status"]["short"]
            if status in DONE:
                if publish(final_message(m)):
                    s["done"] = True
            elif status in CANCELLED:
                s["done"] = True
            else:
                miss(s)
        for fid in batch:
            if fid not in found:
                miss(state[fid])


def main():
    if TEST_POST:
        ok = publish("✅ Test : le bot de scores fonctionne.")
        sys.exit(0 if ok else 1)

    state = load_state()
    live = api_get(f"/fixtures?live={LEAGUES}")
    print(f"{len(live)} match(s) en direct. Requêtes restantes aujourd'hui : {remaining}")
    seen = set()
    for m in live:
        seen.add(str(m["fixture"]["id"]))
        process_live(m, state)
    process_finished(state, seen)

    state = {k: v for k, v in state.items() if not v.get("done")}
    if not DRY_RUN:
        save_state(state)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
    
