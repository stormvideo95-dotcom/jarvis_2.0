"""Choose which Nest / Cast speaker Jarvis talks on.

Run on the Umbrel (while Jarvis is running):
    docker exec -it jarvis python -m app.pick_speaker

Your choice is saved in /data/speaker.json and Jarvis switches right away.
"""
import json
import sys
import time

from . import config


def discover(seconds: int = 8):
    from pychromecast.discovery import discover_chromecasts

    print(f"Zoeken naar speakers op je wifi ({seconds} s)...")
    infos, browser = discover_chromecasts(timeout=seconds)
    try:
        browser.stop_discovery()
    except Exception:
        pass
    found, seen = [], set()
    for info in infos:
        if info.uuid in seen:
            continue
        seen.add(info.uuid)
        found.append({"name": info.friendly_name, "ip": info.host, "model": info.model_name or "?"})
    found.sort(key=lambda d: d["name"].lower())
    return found


def current() -> dict:
    try:
        with open(config.SPEAKER_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"name": config.NEST_NAME, "ip": config.NEST_IP}


def main():
    now = current()
    print("\n  Jarvis 2.0 · speaker kiezen")
    print(f"  Nu: {now.get('name') or now.get('ip') or 'automatisch'}\n")
    speakers = discover()
    if not speakers:
        print("Geen speakers gevonden. Staat de Nest aan en op dezelfde wifi als de Pi?")
        sys.exit(1)
    for i, s in enumerate(speakers, 1):
        mark = "  <- nu" if s["name"] == now.get("name") else ""
        print(f"  {i}. {s['name']:<28} {s['model']:<18} {s['ip']}{mark}")
    print("\n  0. Annuleren")
    while True:
        choice = input("\nKies een nummer: ").strip()
        if choice == "0":
            print("Niets veranderd.")
            return
        if choice.isdigit() and 1 <= int(choice) <= len(speakers):
            break
        print("Dat nummer staat niet in de lijst.")
    pick = speakers[int(choice) - 1]
    pick["chosen_at"] = time.strftime("%Y-%m-%d %H:%M")
    with open(config.SPEAKER_FILE, "w", encoding="utf-8") as f:
        json.dump(pick, f, ensure_ascii=False, indent=2)
    print(f"\nKlaar! Jarvis praat nu via: {pick['name']} ({pick['ip']})")


if __name__ == "__main__":
    main()
