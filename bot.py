"""SONDE : teste l'API publique d'ESPN depuis GitHub. Ne publie RIEN sur Facebook."""
import json
import urllib.error
import urllib.request

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SLUGS = [
    "uefa.champions",
    "uefa.europa",
    "uefa.europa.conf",
    "eng.1",
    "esp.1",
    "ita.1",
    "ger.1",
    "fra.1",
    "all",
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def describe(ev):
    comp = ev["competitions"][0]
    st = ev["status"]
    home = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
    away = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
    return (
        f"{st['type'].get('state')} | horloge {st.get('displayClock')} | "
        f"{st['type'].get('shortDetail')} | "
        f"{home['team']['displayName']} {home.get('score')}-{away.get('score')} "
        f"{away['team']['displayName']} | evenements={len(comp.get('details', []))}"
    )


def main():
    sample = None
    for slug in SLUGS:
        try:
            data = get(f"{BASE}/{slug}/scoreboard")
        except urllib.error.HTTPError as e:
            print(f"== {slug} : ERREUR HTTP {e.code}")
            continue
        except Exception as e:
            print(f"== {slug} : ERREUR {e}")
            continue
        events = data.get("events", [])
        print(f"== {slug} : {len(events)} match(s)")
        for ev in events[:3]:
            try:
                print("   " + describe(ev))
            except Exception as e:
                print(f"   (lecture impossible : {e})")
        if slug != "all" and events:
            states = {
                e["status"]["type"].get("state"): e for e in events if "status" in e
            }
            pick = states.get("in") or states.get("post") or events[0]
            if sample is None:
                sample = (slug, pick)

    if sample:
        slug, ev = sample
        print(f"\n--- DETAIL d'un match ({slug}) ---")
        try:
            data = get(f"{BASE}/{slug}/summary?event={ev['id']}")
            print("Cles :", ", ".join(list(data.keys())[:12]))
            for t in data.get("boxscore", {}).get("teams", []):
                names = [
                    f"{s.get('name')}={s.get('displayValue')}"
                    for s in t.get("statistics", [])
                ]
                print(t.get("team", {}).get("displayName"), "->", "; ".join(names[:20]))
        except Exception as e:
            print("ERREUR detail :", e)


if __name__ == "__main__":
    main()
    
