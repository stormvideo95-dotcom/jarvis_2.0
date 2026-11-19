"""Home Assistant link: Jarvis reads your devices and can switch them.

Only devices in HA_DOMAINS can be controlled (lights, plugs, scenes... never locks
or alarms unless you add them yourself). Temperature/humidity sensors are read-only.
"""
import json
import time
import urllib.request

from . import config

READ_ONLY_CLASSES = {"temperature", "humidity"}
SERVICES = {"turn_on", "turn_off", "toggle", "set_temperature"}

_cache = {"t": 0.0, "states": []}


def enabled() -> bool:
    return bool(config.HA_TOKEN)


def _req(method: str, path: str, body: dict | None = None, timeout: float = 6.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        config.HA_URL.rstrip("/") + path, data=data, method=method,
        headers={"Authorization": f"Bearer {config.HA_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def ping() -> bool:
    try:
        return bool(enabled() and _req("GET", "/api/", timeout=3))
    except Exception:
        return False


def _states() -> list:
    if time.time() - _cache["t"] > 30:
        _cache["states"] = _req("GET", "/api/states")
        _cache["t"] = time.time()
    return _cache["states"]


def devices() -> list[dict]:
    """Controllable devices + read-only climate sensors, small enough for the AI prompt."""
    out = []
    for s in _states():
        eid = s.get("entity_id", "")
        domain = eid.split(".")[0]
        attrs = s.get("attributes", {})
        name = attrs.get("friendly_name") or eid
        if domain in config.HA_DOMAINS:
            out.append({"id": eid, "name": name, "state": s.get("state"), "control": True})
        elif domain == "sensor" and attrs.get("device_class") in READ_ONLY_CLASSES:
            unit = attrs.get("unit_of_measurement", "")
            out.append({"id": eid, "name": name, "state": f"{s.get('state')} {unit}".strip(), "control": False})
    return out[:80]


def prompt_block() -> str:
    """Text added to the AI's instructions so it knows your house."""
    if not enabled():
        return ""
    try:
        devs = devices()
    except Exception as e:
        return f"\n(Home Assistant is niet bereikbaar: {type(e).__name__}. Zeg dat als iemand een apparaat wil bedienen.)\n"
    if not devs:
        return ""
    lines = [f"- {d['id']} | {d['name']} | {d['state']}{'' if d['control'] else ' | alleen lezen'}" for d in devs]
    return (
        "\nHUIS (Home Assistant). Apparaten (id | naam | status):\n" + "\n".join(lines) +
        "\n\nOm apparaten te bedienen gebruik je deze actie:\n"
        '{"type": "home", "service": "turn_on" | "turn_off" | "toggle" | "set_temperature", '
        '"entities": ["light.xxx", ...], "brightness": <0-100, optioneel>, "temperature": <getal, alleen thermostaat>}\n'
        "Gebruik alleen id's uit de lijst. 'De lichten' zonder kamer = alle light.* apparaten. "
        "Vragen over de status (aan/uit, temperatuur) beantwoord je met de lijst, zonder actie.\n"
        'Voorbeeld: "doe de lichten aan" -> {"say": "Lichten gaan aan.", "action": {"type": "home", '
        '"service": "turn_on", "entities": ["light.slaapkamer", "light.bureau"]}}\n'
    )


def run(action: dict) -> str | None:
    """Carry out a 'home' action. Returns an error text for Jarvis to say, or None."""
    service = action.get("service")
    if service not in SERVICES:
        return "Dat kan ik niet met dat apparaat."
    allowed = {d["id"] for d in devices() if d["control"]}
    ids = [e for e in (action.get("entities") or []) if e in allowed]
    if not ids:
        return "Ik vond dat apparaat niet in Home Assistant."
    errors = 0
    for domain in sorted({e.split(".")[0] for e in ids}):
        group = [e for e in ids if e.startswith(domain + ".")]
        svc, body = service, {"entity_id": group}
        if domain == "scene":
            svc = "turn_on"
        if service == "set_temperature":
            if domain != "climate" or action.get("temperature") is None:
                continue
            body["temperature"] = action["temperature"]
        elif service == "turn_on" and domain == "light" and action.get("brightness") is not None:
            body["brightness_pct"] = max(1, min(100, int(action["brightness"])))
        try:
            _req("POST", f"/api/services/{domain}/{svc}", body)
        except Exception:
            errors += 1
    _cache["t"] = 0  # states changed, refresh next time
    return "Home Assistant gaf een fout." if errors else None
