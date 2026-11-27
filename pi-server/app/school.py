"""School buddy: Jarvis knows Storm's school week.

- Reads the LAB project site (Z-route) for this week's pages, success criteria and links.
- Storm scans his planner and studiewijzer every week with the Jarvis School app.
  Jarvis saves them as PDF (in Google Drive, "Jarvis School/Week 03 · 23–27 nov") and
  reads them with an NVIDIA vision model to find tests and tasks.
- Chat in the app (text, with link buttons); voice questions about school use the same brain.
- "Ik ben mijn Franse taak vergeten" -> Jarvis keeps it as a task.
- The evening before a test Jarvis says it on the Nest and offers a 10-question quiz
  made from the success criteria. Monday evening it asks for the new planner if it's missing.

Everything lives in /data/school/ (school.json + the PDFs).
"""
import base64
import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import brain, config

log = logging.getLogger("jarvis.school")
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Brussels"))
DIR = os.path.join(os.path.dirname(config.SPEAKER_FILE), "school")
FILE = os.path.join(DIR, "school.json")
_lock = threading.RLock()

KINDS = {"planner": "Planner", "studiewijzer": "Studiewijzer", "andere": "Document"}
MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
DAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
SUBJECTS = [  # (slug start on the project site, name)
    ("2-natuurwetenschappen", "NW"), ("4-cultuurbeschouwing", "Cultuurbeschouwing"),
    ("5-nederlands", "Nederlands"), ("6-wiskunde", "Wiskunde"), ("7-fran", "Frans"),
    ("8-engels", "Engels"), ("9-techniek", "Techniek"), ("projecturen", "Projecturen"),
]
SAFE_HOSTS = ("sites.google.com", "docs.google.com", "drive.google.com", "study.ictstorm.com",
              "labonderwijs-evaluaties.firebaseapp.com")


# ---- storage ---------------------------------------------------------------------
def _load() -> dict:
    try:
        with open(FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    for k, v in (("weeks", {}), ("notes", []), ("chat", []), ("missed", []), ("said", {})):
        s.setdefault(k, v)
    return s


def _save(s: dict):
    os.makedirs(DIR, exist_ok=True)
    s["chat"] = s["chat"][-200:]
    s["missed"] = s["missed"][-60:]
    s["said"] = dict(list(s["said"].items())[-60:])
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, FILE)


def _week(s: dict, n: int) -> dict:
    w = s["weeks"].setdefault(str(n), {})
    for k in ("docs", "tests", "tasks"):
        w.setdefault(k, [])
    return w


# ---- school weeks ----------------------------------------------------------------
def now() -> datetime:
    return datetime.now(TZ)


def _week1() -> date:
    try:
        return date.fromisoformat(config.SCHOOL_WEEK1)
    except ValueError:
        return date(2026, 11, 9)


def week_of(d: date) -> int:
    monday = d - timedelta(days=d.weekday())
    return (monday - _week1()).days // 7 + 1


def current_week() -> int:
    return week_of(now().date())


def week_days(n: int) -> tuple[date, date]:
    mon = _week1() + timedelta(weeks=n - 1)
    return mon, mon + timedelta(days=4)


def week_label(n: int) -> str:
    mon, fri = week_days(n)
    if mon.month == fri.month:
        span = f"{mon.day}–{fri.day} {MONTHS[fri.month - 1]}"
    else:
        span = f"{mon.day} {MONTHS[mon.month - 1]}–{fri.day} {MONTHS[fri.month - 1]}"
    return f"Week {n} · {span}"


def _folder_name(n: int) -> str:
    return f"Week {n:02d} · " + week_label(n).split(" · ", 1)[1]


def nice_date(iso: str | None) -> str:
    try:
        d = date.fromisoformat(iso or "")
    except ValueError:
        return ""
    today = now().date()
    if d == today:
        return "vandaag"
    if d == today + timedelta(days=1):
        return "morgen"
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


# ---- project site ----------------------------------------------------------------
_cache: dict = {}


def _get(url: str, ttl: int = 6 * 3600) -> str:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    parts = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit((parts.scheme, parts.netloc, urllib.parse.quote(parts.path, safe="/-_.~%"), parts.query, ""))
    req = urllib.request.Request(safe, headers={"User-Agent": "Mozilla/5.0 Jarvis-2.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8", "replace")
    _cache[url] = (time.time(), body)
    return body


def _text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|header)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|section)>", "\n", page)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in page.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _base() -> str:
    return config.SCHOOL_SITE.rsplit("/", 1)[0] if config.SCHOOL_SITE.rstrip("/").endswith("homepage") \
        else config.SCHOOL_SITE.rstrip("/")


def site_links() -> list[dict]:
    """Every page of the project site: [{"url", "slug", "title"}]."""
    if not config.SCHOOL_SITE:
        return []
    try:
        page = _get(config.SCHOOL_SITE)
    except Exception as e:
        log.info("project site not reachable: %s", e)
        return []
    base = _base()
    prefix = urllib.parse.urlsplit(base).path.rstrip("/")
    out, seen = [], set()
    for href, inner in re.findall(r'(?is)<a[^>]+href="([^"#?]+)"[^>]*>(.*?)</a>', page):
        path = urllib.parse.unquote(urllib.parse.urlsplit(html.unescape(href)).path)
        if not path.startswith(prefix + "/"):
            continue
        slug = path[len(prefix) + 1:].strip("/")
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append({"url": f"{base}/{slug}", "slug": slug, "title": title or slug.rsplit("/", 1)[-1]})
    return out


def subject_of(slug: str) -> str:
    for start, name in SUBJECTS:
        if slug.startswith(start):
            return name
    return ""


def _is_week(slug: str, n: int) -> bool:
    last = slug.rsplit("/", 1)[-1].lower()
    return bool(re.match(rf"^(w|week-?|semaine-?){n}(\b|[-_]|$)", last))


def week_pages(n: int, subject: str | None = None) -> list[dict]:
    """This week's pages; for NW only Storm's route (Z)."""
    route = f"/{config.SCHOOL_ROUTE.lower()}-route/"
    pages = []
    for ln in site_links():
        s = ln["slug"].lower()
        if not _is_week(s, n) or "correction" in s:
            continue
        if "-route/" in s and route not in s:
            continue
        subj = subject_of(s)
        if subject and subj.lower() != subject.lower():
            continue
        pages.append({**ln, "subject": subj, "week": n})
    return pages


def page_text(url: str, limit: int = 4000, from_criteria: bool = False) -> str:
    try:
        t = _text(_get(url))
    except Exception:
        return ""
    if from_criteria:
        i = t.lower().find("succescriteria")
        if i > 0:
            t = t[i:]
    return t[:limit]


def criteria_material(subject: str, upto_week: int, what: str = "") -> str:
    """Success criteria of this subject for the test (this week and the 2 weeks before)."""
    parts = [f"Toets: {what}"] if what else []
    for n in range(upto_week, max(0, upto_week - 3), -1):
        for p in week_pages(n, subject):
            txt = page_text(p["url"], 3500, from_criteria=True)
            if txt:
                parts.append(f"--- {p['title']} (week {n}) ---\n{txt}")
    return "\n\n".join(parts)[:12000]


# ---- Google Drive (Apps Script web app on Storm's account) -------------------------
def drive_on() -> bool:
    return bool(config.DRIVE_SCRIPT_URL and config.DRIVE_SECRET)


def _drive(body: dict, timeout: float = 60) -> dict:
    data = json.dumps({**body, "secret": config.DRIVE_SECRET}).encode()
    req = urllib.request.Request(config.DRIVE_SCRIPT_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # Apps Script answers via a redirect
        res = json.loads(r.read() or b"{}")
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "Drive script gave no ok")
    return res


def drive_ping() -> str:
    if not drive_on():
        return "niet gekoppeld"
    try:
        return "verbonden" if _drive({"action": "ping"}, timeout=20).get("ok") else "fout"
    except Exception as e:
        return f"fout: {e}"[:80]


def _to_drive(n: int, doc: dict):
    path = os.path.join(DIR, f"week-{n}", doc["name"])
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    res = _drive({"action": "save", "folder": _folder_name(n), "name": doc["name"],
                  "mime": "application/pdf", "data": b64})
    with _lock:
        s = _load()
        for d in _week(s, n)["docs"]:
            if d["id"] == doc["id"]:
                d["url"], d["folder_url"] = res.get("url"), res.get("folderUrl")
        _save(s)
    return res.get("url")


def retry_drive():
    if not drive_on():
        return
    with _lock:
        todo = [(int(n), d) for n, w in _load()["weeks"].items() for d in w.get("docs", []) if not d.get("url")]
    for n, d in todo[:5]:
        try:
            _to_drive(n, d)
        except Exception as e:
            log.info("Drive retry failed: %s", e)
            return


# ---- reading scans with a vision model ------------------------------------------------
VISION_MODELS = ["meta/llama-4-maverick-17b-128e-instruct", "meta/llama-3.2-90b-vision-instruct",
                 "microsoft/phi-4-multimodal-instruct", "nvidia/nemotron-nano-12b-v2-vl",
                 "meta/llama-3.2-11b-vision-instruct"]
_vision_ok: str | None = None


def _vision(prompt: str, jpeg_b64: str) -> str:
    global _vision_ok
    order = [m for m in [config.VISION_MODEL, _vision_ok] if m] + VISION_MODELS
    client = brain._llm().with_options(timeout=90.0)
    last = None
    for model in list(dict.fromkeys(order)):
        try:
            resp = client.chat.completions.create(
                model=model, temperature=0.1, max_tokens=1500,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}}]}])
            text = brain._text_of(resp.choices[0].message)
            if text:
                _vision_ok = model
                return text
        except Exception as e:
            log.info("vision %s failed: %s", model, str(e)[:200])
            last = e
    raise RuntimeError(f"no vision model answered: {last}")


def _json_obj(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b <= a:
        return {}
    try:
        return json.loads(raw[a:b + 1])
    except ValueError:
        return {}


def _read_page(kind: str, n: int, jpeg_b64: str) -> dict:
    mon, _ = week_days(n)
    days = ", ".join(f"{DAYS[i]} = {(mon + timedelta(days=i)).isoformat()}" for i in range(7))
    prompt = (f"Dit is een foto van de {kind} van Storm (1e middelbaar, LAB-school) voor {week_label(n)}. "
              f"Dagen: {days}. Volgende week begint op {(mon + timedelta(weeks=1)).isoformat()}.\n"
              "Lees alle toetsen (toets, test, procestoets, evaluatie, overhoring) en taken (opdracht, huiswerk, "
              "meebrengen, deadline, indienen). Zet dagen om naar een datum. Geef ALLEEN JSON:\n"
              '{"tests": [{"date": "YYYY-MM-DD of null", "subject": "vak", "what": "wat de toets is"}], '
              '"tasks": [{"date": "YYYY-MM-DD of null", "subject": "vak", "what": "wat moet"}], '
              '"summary": "1 zin over wat er op deze pagina staat"}')
    return _json_obj(_vision(prompt, jpeg_b64))


def _clean_items(items, n: int, source: str) -> list:
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not str(it.get("what") or "").strip():
            continue
        d = str(it.get("date") or "")
        try:
            d = date.fromisoformat(d).isoformat()
        except ValueError:
            d = None
        out.append({"id": uuid.uuid4().hex[:8], "date": d, "subject": str(it.get("subject") or "")[:40],
                    "what": str(it["what"])[:200], "source": source, "week": n})
    return out


def _process(n: int, doc: dict, pages: list[str]):
    """Background: Drive upload + read the pages, then tell Storm in the chat."""
    url = None
    if drive_on():
        try:
            url = _to_drive(n, doc)
        except Exception as e:
            log.warning("Drive upload failed (will retry): %s", e)
    tests, tasks, summaries, failed = [], [], [], 0
    for jpeg in pages[:12]:
        try:
            r = _read_page(KINDS[doc["kind"]].lower(), n, jpeg)
        except Exception as e:
            log.warning("reading page failed: %s", e)
            failed += 1
            continue
        tests += _clean_items(r.get("tests"), n, doc["kind"])
        tasks += _clean_items(r.get("tasks"), n, doc["kind"])
        if r.get("summary"):
            summaries.append(str(r["summary"])[:200])
    with _lock:
        s = _load()
        w = _week(s, n)
        if tests or tasks:   # a new scan of the same kind replaces what the old one said
            w["tests"] = [t for t in w["tests"] if t.get("source") != doc["kind"]] + tests
            w["tasks"] = [t for t in w["tasks"] if t.get("source") != doc["kind"]] + tasks
        _save(s)
    name = KINDS[doc["kind"]].lower()
    if failed and failed == len(pages):
        msg = f"Ik heb je {name} van week {n} bewaard, maar ik kon hem niet lezen. Probeer een scherpere scan?"
    else:
        lines = [f"Ik heb je {name} van week {n} gelezen."]
        for t in sorted(tests, key=lambda x: x["date"] or "9"):
            lines.append(f"- Toets {t['subject']}: {t['what']}" + (f" ({nice_date(t['date'])})" if t["date"] else ""))
        for t in sorted(tasks, key=lambda x: x["date"] or "9")[:8]:
            lines.append(f"- {t['subject']}: {t['what']}" + (f" ({nice_date(t['date'])})" if t["date"] else ""))
        if not tests and not tasks:
            lines.append("Ik vond er geen toetsen of taken op." + (f" {summaries[0]}" if summaries else ""))
        msg = "\n".join(lines)
    buttons = [{"label": f"Open {name}", "url": url}] if url else []
    add_chat("jarvis", msg, buttons)


def upload(kind: str, week: int | None, pdf_b64: str, pages: list[str]) -> dict:
    kind = kind if kind in KINDS else "andere"
    n = int(week or current_week())
    if not 1 <= n <= 60:
        raise ValueError("week moet tussen 1 en 60 liggen")
    pdf = base64.b64decode(pdf_b64 or "", validate=False)
    if not pdf.startswith(b"%PDF"):
        raise ValueError("geen PDF ontvangen")
    os.makedirs(os.path.join(DIR, f"week-{n}"), exist_ok=True)
    with _lock:
        s = _load()
        w = _week(s, n)
        base = f"{KINDS[kind]} week {n}"
        name = f"{base}.pdf"
        if kind == "andere":
            count = sum(1 for d in w["docs"] if d["kind"] == "andere") + 1
            name = f"{base} - {count}.pdf"
        w["docs"] = [d for d in w["docs"] if d["name"] != name]
        doc = {"id": uuid.uuid4().hex[:8], "kind": kind, "name": name, "pages": len(pages),
               "added": now().isoformat(timespec="minutes"), "url": None}
        w["docs"].append(doc)
        with open(os.path.join(DIR, f"week-{n}", name), "wb") as f:
            f.write(pdf)
        _save(s)
    threading.Thread(target=_process, args=(n, doc, pages), daemon=True).start()
    return {"ok": True, "week": n, "label": week_label(n), "doc": doc, "drive": drive_on()}


def file_path(week: int, name: str) -> str | None:
    p = os.path.join(DIR, f"week-{int(week)}", os.path.basename(name))
    return p if os.path.isfile(p) else None


# ---- notes ("ik ben X vergeten") ------------------------------------------------------
def _open_notes(s: dict) -> list:
    return [x for x in s["notes"] if not x.get("done")]


def remember(items: list, done_ids: list):
    with _lock:
        s = _load()
        for it in _clean_items(items, current_week(), "chat"):
            if not any(x["what"].lower() == it["what"].lower() and not x.get("done") for x in s["notes"]):
                s["notes"].append({**it, "kind": "test" if "toets" in it["what"].lower() else "task",
                                   "done": False, "added": now().isoformat(timespec="minutes")})
        for x in s["notes"]:
            if x["id"] in (done_ids or []):
                x["done"] = True
        _save(s)


# ---- chat --------------------------------------------------------------------------------
def add_chat(role: str, text: str, buttons: list | None = None) -> dict:
    msg = {"id": uuid.uuid4().hex[:10], "role": role, "text": text, "buttons": buttons or [],
           "time": now().isoformat(timespec="seconds")}
    with _lock:
        s = _load()
        s["chat"].append(msg)
        _save(s)
    return msg


def chat_history(after: str = "") -> list:
    msgs = _load()["chat"]
    if after:
        ids = [m["id"] for m in msgs]
        if after in ids:
            return msgs[ids.index(after) + 1:]
    return msgs[-80:]


def _upcoming(s: dict, days: int = 14) -> list:
    today = now().date().isoformat()
    end = (now().date() + timedelta(days=days)).isoformat()
    items = []
    for w in s["weeks"].values():
        for t in w.get("tests", []):
            items.append({**t, "kind": "test"})
        for t in w.get("tasks", []):
            items.append({**t, "kind": "task"})
    items += [{**x} for x in _open_notes(s)]
    return sorted([i for i in items if not i.get("date") or today <= i["date"] <= end],
                  key=lambda i: i.get("date") or "9")


def _context() -> tuple[str, list]:
    s = _load()
    n = current_week()
    links = []
    lines = [f"Vandaag: {DAYS[now().weekday()]} {now().date().isoformat()} {now().strftime('%H:%M')}. "
             f"Het is {week_label(n)} (schoolweek {n}). Storm volgt overal de {config.SCHOOL_ROUTE.upper()}-route."]
    up = _upcoming(s)
    lines.append("\nTOETSEN EN TAKEN (uit planner, studiewijzer en wat Storm zei):")
    for i in up[:30]:
        tag = "TOETS" if i["kind"] == "test" else "TAAK"
        lines.append(f"- [{tag}] {i.get('date') or 'geen datum'} {i.get('subject', '')}: {i['what']}"
                     + (f" (id {i['id']})" if i.get("source") == "chat" or i.get("added") else ""))
    if not up:
        lines.append("- (nog niets bekend; vraag Storm om zijn planner te scannen)")
    if s["missed"]:
        lines.append("\nFOUT BEANTWOORD IN DE LAATSTE QUIZ:")
        lines += [f"- {m['q']} -> {m['a']}" for m in s["missed"][-8:]]
    docs = _week(s, n)["docs"]
    if docs:
        lines.append("\nDOCUMENTEN DEZE WEEK (Drive):")
        for d in docs:
            if d.get("url"):
                links.append(d["url"])
                lines.append(f"- {d['name']}: {d['url']}")
    pages = week_pages(n) + week_pages(n + 1)
    if pages:
        lines.append("\nPROJECTSITE (deze week):")
        budget = 9000
        for p in pages:
            links.append(p["url"])
            txt = page_text(p["url"], 2200) if budget > 0 else ""
            budget -= len(txt)
            lines.append(f"\n## {p['subject']} - {p['title']} (week {p['week']}): {p['url']}\n{txt}")
    for extra in ("homepage", "planningen-studiewijzers-evaluatie-app"):
        for ln in site_links():
            if ln["slug"] == extra:
                links.append(ln["url"])
                lines.append(f"Link: {ln['title']}: {ln['url']}")
    links.append(config.STUDY_URL.rstrip("/"))
    lines.append(f"Link: Storm Study (oefenen): {config.STUDY_URL.rstrip('/')}")
    return "\n".join(lines), links


CHAT_PROMPT = """Je bent Jarvis, de schoolbuddy van Storm (1e middelbaar, LAB-school in Sint-Amands, België).
Je helpt hem niets te vergeten: toetsen, taken, opdrachten en succescriteria. Wees vriendelijk en kort.
{mode}
Antwoord in het Nederlands. Geef ALLEEN één JSON-object terug:
{{"say": "<je antwoord>",
  "buttons": [{{"label": "<max 4 woorden>", "url": "<ALLEEN een url uit de context>"}}],
  "remember": [{{"date": "YYYY-MM-DD of null", "subject": "<vak>", "what": "<wat hij moet doen of de toets>"}}],
  "done": ["<id van een taak die nu klaar is>"],
  "quiz": "<vak als hij overhoord wil worden of wil studeren voor een toets, anders null>"}}
Regels:
- Zegt Storm dat hij iets vergeten is, iets moet doen, of een toets heeft: zet het in "remember" (met datum als je die weet).
- Zegt hij dat iets klaar is: zet de id in "done".
- Geef 0 tot 3 knoppen naar de juiste pagina (opdracht, succescriteria, document, Storm Study). Verzin nooit een url.
- Weet je iets niet zeker (geen planner gescand), zeg dat eerlijk.

CONTEXT:
{context}"""


def ask(text: str, voice: bool = False) -> dict:
    """One chat turn. Returns {"say", "buttons", "quiz"} and stores both messages."""
    add_chat("storm", text)
    context, links = _context()
    mode = ("Je praat via een speaker: maximaal 2 zinnen, geen lijstjes, geen urls uitspreken."
            if voice else "Je chat in een app: maximaal 6 zinnen, korte lijstjes met '- ' mogen, geen koppen.")
    hist = [{"role": "user" if m["role"] == "storm" else "assistant", "content": m["text"]}
            for m in _load()["chat"][-9:-1]]
    try:
        raw = brain._chat([{"role": "system", "content": CHAT_PROMPT.format(mode=mode, context=context)},
                           *hist, {"role": "user", "content": text}], max_tokens=900, temperature=0.3)
        data = _json_obj(raw) or {"say": raw.strip()[:600]}
    except Exception as e:
        log.warning("school chat failed: %s", e)
        data = {"say": "Sorry, ik kan nu even niet nadenken (de AI antwoordt niet). Probeer zo opnieuw."}
    say = str(data.get("say") or "").strip() or "Oké."
    buttons = []
    for b in data.get("buttons") or []:
        if not isinstance(b, dict):
            continue
        url, label = str(b.get("url") or "").strip(), str(b.get("label") or "").strip()[:30]
        host = urllib.parse.urlsplit(url).hostname or ""
        if url and label and (url in links or host.endswith(SAFE_HOSTS)) and url.startswith("https://"):
            buttons.append({"label": label, "url": url})
    remember(data.get("remember") or [], [str(i) for i in data.get("done") or []])
    quiz = data.get("quiz")
    quiz = quiz if isinstance(quiz, str) and quiz.strip().lower() not in ("", "null", "none") else None
    if quiz and not voice:
        say += f"\n\nWil je dat ik je overhoor? Zeg thuis: \"Jarvis, overhoor me voor {subject_name(quiz)}\"."
    msg = add_chat("jarvis", say, buttons[:3])
    return {**msg, "quiz": quiz}


def quiz_for(subject: str) -> dict:
    """What a 10-question quiz on this subject should use."""
    s = _load()
    test = next((t for t in _upcoming(s, 21) if t["kind"] == "test" and subject.lower() in t.get("subject", "").lower()), None)
    n = week_of(date.fromisoformat(test["date"])) if test and test.get("date") else current_week()
    n = min(n, current_week())
    material = criteria_material(subject_name(subject), n, test["what"] if test else "")
    label = f"je toets {subject_name(subject)}" if test else subject_name(subject)
    return {"label": label, "material": material, "french": subject_name(subject) == "Frans"}


def subject_name(text: str) -> str:
    t = (text or "").lower()
    for key, name in (("nw", "NW"), ("natuur", "NW"), ("wisk", "Wiskunde"), ("frans", "Frans"), ("fran", "Frans"),
                      ("engels", "Engels"), ("english", "Engels"), ("neder", "Nederlands"), ("cultuur", "Cultuurbeschouwing"),
                      ("techn", "Techniek"), ("project", "Projecturen")):
        if key in t:
            return name
    return (text or "").strip()[:30] or "NW"


def quiz_done(missed: list, correct: int, answered: int):
    if not answered:
        return
    with _lock:
        s = _load()
        s["missed"] = (s["missed"] + missed)[-60:]
        _save(s)
    if missed:
        lines = [f"Quiz klaar: {correct} van {answered} juist. Deze oefenen we nog eens:"]
        lines += [f"- {m['q']} → {m['a']}" for m in missed[:10]]
        add_chat("jarvis", "\n".join(lines), [{"label": "Oefen op Storm Study", "url": config.STUDY_URL.rstrip("/")}])
    else:
        add_chat("jarvis", f"Quiz klaar: {correct} van {answered} juist. Je bent klaar voor je toets! 💪")


# ---- reminders on the Nest -----------------------------------------------------------------
pending: dict = {}


def _hhmm(v: str, default: str) -> tuple[int, int]:
    try:
        h, m = (v or default).split(":")
        return int(h), int(m)
    except ValueError:
        h, m = default.split(":")
        return int(h), int(m)


def _due(at: str, default: str, window_min: int = 120) -> bool:
    h, m = _hhmm(at, default)
    start = now().replace(hour=h, minute=m, second=0, microsecond=0)
    return start <= now() < start + timedelta(minutes=window_min)


def check_reminders(say, listen_say):
    """Called every minute. Speaks at most once per kind per day."""
    s = _load()
    today = now().date()
    key = today.isoformat()
    if _due(config.SCHOOL_REMIND, "19:00") and not s["said"].get(key + ":evening"):
        tomorrow = (today + timedelta(days=1)).isoformat()
        items = [i for i in _upcoming(s, 1) if i.get("date") == tomorrow]
        with _lock:
            s = _load()
            s["said"][key + ":evening"] = True
            _save(s)
        tests = [i for i in items if i["kind"] == "test"]
        tasks = [i for i in items if i["kind"] != "test"]
        if tests:
            subj = tests[0].get("subject") or "je toets"
            what = " en ".join(f"{t.get('subject', '')} ({t['what']})" for t in tests[:2])
            extra = f" En vergeet niet: {tasks[0]['what']}." if tasks else ""
            text = f"Hé Storm, morgen heb je een toets: {what}.{extra} Zullen we even studeren? Zeg ja of nee."
            pending.update(kind="quiz", subject=subj, until=time.time() + 120)
            pages = week_pages(current_week(), subject_name(subj))
            add_chat("jarvis", text.replace(" Zeg ja of nee.", ""),
                     [{"label": "Succescriteria", "url": pages[0]["url"]}] if pages else [])
            listen_say(text)
        elif tasks:
            text = "Hé Storm, vergeet morgen niet: " + "; ".join(t["what"] for t in tasks[:3]) + "."
            add_chat("jarvis", text)
            say(text)
    if today.weekday() == 0 and _due(config.SCHOOL_PLANNER_REMIND, "18:00") and not s["said"].get(key + ":planner"):
        with _lock:
            s = _load()
            s["said"][key + ":planner"] = True
            have = {d["kind"] for d in _week(s, current_week())["docs"]}
            _save(s)
        missing = [KINDS[k].lower() for k in ("planner", "studiewijzer") if k not in have]
        if missing:
            text = f"Hé Storm, scan je {' en '.join(missing)} van deze week even in de Jarvis School app?"
            add_chat("jarvis", text)
            say(text)


YES = r"\b(ja|jaa|jep|yes|oké|oke|ok|goed|graag|zeker|doe maar|is goed|tuurlijk|natuurlijk)\b"
NO = r"\b(nee|neen|no|nope|niet|later|straks|morgen)\b"


def answer_pending(text: str) -> dict | None:
    """Reply to 'Zullen we even studeren?'. Returns {"say", "quiz"} or None if not about it."""
    if not pending or time.time() > pending.get("until", 0):
        pending.clear()
        return None
    t = (text or "").lower()
    subj = pending.get("subject", "")
    if re.search(NO, t):
        pending.clear()
        return {"say": "Oké, succes morgen! Je kan altijd zeggen: overhoor me.", "quiz": None}
    if re.search(YES, t):
        pending.clear()
        return {"say": "", "quiz": quiz_for(subj)}
    pending.clear()
    return None


def start_reminders(say, listen_say):
    def loop():
        time.sleep(20)
        while True:
            try:
                check_reminders(say, listen_say)
                retry_drive()
            except Exception:
                log.exception("school reminder failed")
            time.sleep(60)
    threading.Thread(target=loop, daemon=True).start()


# ---- app overview ----------------------------------------------------------------------------
def state() -> dict:
    s = _load()
    n = current_week()
    weeks = []
    for k in sorted(s["weeks"], key=int, reverse=True):
        w = s["weeks"][k]
        weeks.append({"week": int(k), "label": week_label(int(k)), "folder": _folder_name(int(k)),
                      "docs": w.get("docs", []), "tests": w.get("tests", []), "tasks": w.get("tasks", [])})
    if not any(w["week"] == n for w in weeks):
        weeks.insert(0, {"week": n, "label": week_label(n), "folder": _folder_name(n), "docs": [], "tests": [], "tasks": []})
    return {"week": n, "label": week_label(n), "weeks": weeks, "notes": _open_notes(s),
            "upcoming": _upcoming(s), "drive": drive_on(), "site": bool(config.SCHOOL_SITE)}


def status() -> dict:
    s = _load()
    return {"week": current_week(), "docs": sum(len(w.get("docs", [])) for w in s["weeks"].values()),
            "upcoming": len(_upcoming(s)), "drive": "gekoppeld" if drive_on() else "niet gekoppeld"}
