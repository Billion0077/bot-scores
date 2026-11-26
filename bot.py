import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FOOTBALL_KEY = os.environ["FOOTBALL_DATA_KEY"]
PAGE_ID = os.environ["FB_PAGE_ID"]
PAGE_TOKEN = os.environ["FB_PAGE_TOKEN"]
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# LDC, Liga, Premier League, Serie A, Bundesliga, Ligue 1
COMPETITIONS = "CL,PD,PL,SA,BL1,FL1"
STATE_FILE = "state.json"
GRAPH_URL = "https://graph.facebook.com/v27.0"

errors = 0


def get_matches():
    url = "https://api.football-data.org/v4/matches?competitions=" + COMPETITIONS
    req = urllib.request.Request(url, headers={"X-Auth-Token": FOOTBALL_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("matches", [])


def publish(message):
    """Publie sur la page Facebook. Renvoie True si c'est réussi."""
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
            print("Publié : " + message.replace("\n", " | "))
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


def process(m, state):
    status = m["status"]
    full = m["score"]["fullTime"]
    if status not in ("IN_PLAY", "PAUSED", "FINISHED") or full["home"] is None:
        return

    mid = str(m["id"])
    s = state.setdefault(mid, {"score": "0-0", "ht": False, "ft": False})
    if s["ft"]:
        return

    cur = f'{full["home"]}-{full["away"]}'
    home = m["homeTeam"].get("shortName") or m["homeTeam"]["name"]
    away = m["awayTeam"].get("shortName") or m["awayTeam"]["name"]
    line = f'{home} {full["home"]} - {full["away"]} {away}'
    comp = m["competition"]["name"]

    if status != "FINISHED" and cur != s["score"]:
        if publish(f"⚽ BUT !\n{line}\n🏆 {comp}"):
            s["score"] = cur

    if status == "PAUSED" and not s["ht"]:
        if publish(f"⏸️ MI-TEMPS\n{line}\n🏆 {comp}"):
            s["ht"] = True

    if status == "FINISHED":
        if publish(f"🏁 TERMINÉ\n{line}\n🏆 {comp}"):
            s["ft"] = True
            s["score"] = cur


def main():
    state = load_state()
    for m in get_matches():
        process(m, state)
    if not DRY_RUN:
        save_state(state)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
      
