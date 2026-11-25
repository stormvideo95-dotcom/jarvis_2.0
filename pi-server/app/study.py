"""Study mode: a spoken quiz from Storm Study (study.ictstorm.com).

  "Jarvis, start study mode"            -> asks what's missing:
     subject/topics  (NW, Frans, HB, "transport en ademhaling", "mijn fouten")
     game            (quiz mix / quiz typ / quiz kahoot)
     count           (a number, or "tot ik stop zeg")
  Everything can also be said in one go:
     "start study mode NW transport en ademhaling, kahoot, 10 vragen"

Questions come from the Storm Study cache (items, orders, mistakes). Without a
Storm Study link it falls back to the bundled leerstof/*.txt + AI questions.
After every answer Jarvis posts it to Storm Study (queued when offline).
French words are wrapped in [[fr:...]] so tts.py can use a French voice.
"""
import difflib
import json
import os
import random
import re
import time
import unicodedata

from . import brain, storm_study

HERE = os.path.join(os.path.dirname(__file__), "leerstof")

# ---- words Jarvis understands ------------------------------------------------------
SUBJECT_WORDS = {
    "nw": ("nw", "n w", "natuurwetenschap", "natuurwetenschappen", "wetenschappen", "biologie", "bio"),
    "frans": ("frans", "francais", "french", "fr"),
    "hb": ("hb", "h b", "historisch", "historisch bewustzijn", "geschiedenis"),
}
TOPIC_WORDS = {
    "cel": ("cel", "cellen", "de cel", "celleer", "organel", "organellen"),
    "adem": ("adem", "ademhaling", "ademhalingsstelsel", "longen", "long", "ademen", "luchtwegen"),
    "trans": ("trans", "transport", "transportstelsel", "bloed", "hart", "bloedsomloop", "bloedvaten", "bloedsomlopen"),
    "corps": ("corps", "le corps", "lichaam", "lichaamsdelen", "lichaamsdeel", "expressions", "uitdrukkingen"),
    "sens": ("sens", "les sens", "cinq sens", "zintuig", "zintuigen", "les cinq sens"),
    "domeinen": ("domeinen", "domein", "de domeinen", "4 domeinen", "vier domeinen", "economisch", "sociaal", "cultureel", "politiek"),
    "begrippen": ("begrippen", "begrip", "bronnen", "bron"),
}
MISTAKE_WORDS = ("mijn fouten", "fouten", "mistakes", "verbeteren", "herhalen")
STOP = ("stop", "stoppen", "genoeg", "einde", "hou op", "ik stop", "ik wil stoppen")
NUMBERS = {"een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8,
           "negen": 9, "tien": 10, "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14, "vijftien": 15,
           "twintig": 20, "vijfentwintig": 25, "dertig": 30, "veertig": 40, "vijftig": 50}
LETTERS = {"a": 0, "aa": 0, "b": 1, "be": 1, "bee": 1, "c": 2, "ce": 2, "cee": 2, "see": 2, "d": 3, "dee": 3}
ARTICLES = {"de", "het", "een", "le", "la", "les", "l", "un", "une", "des", "du", "d", "the", "a"}


def _plain(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower().replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def _core(t: str) -> str:
    """Comparable form: no accents, punctuation, capitals or articles."""
    return " ".join(w for w in _plain((t or "").replace("'", " ")).split() if w not in ARTICLES)


def _has(text: str, phrase: str) -> bool:
    p = _plain(phrase)
    return bool(p) and re.search(rf"\b{re.escape(p)}\b", _plain(text)) is not None


def _wants_stop(text: str) -> bool:
    return any(_has(text, w) for w in STOP)


def fr(text: str) -> str:
    return f"[[fr:{text}]]"


class Session:
    def __init__(self):
        self.active = False
        self.step = None            # pick | game | count | quiz
        self.topic_ids: list = []
        self.use_mistakes = False
        self.label_text = ""
        self.game = None            # kahoot | typ | mix
        self.total = None           # None = until "stop"
        self.count_set = False
        self.pool: list = []
        self.asked_keys: set = set()
        self.current = None
        self.asked_at = 0.0
        self.n = 0
        self.answered = 0
        self.correct = 0
        self.streak = 0
        self.best_streak = 0
        self.silent_turns = 0
        self.fallback_subject = None  # no Storm Study data: bundled txt + AI

    def label(self) -> str:
        return self.label_text or "?"

    # ================================================================ understanding
    def _all_topics(self):
        return storm_study.topics()

    def _subject_of(self, topic: dict):
        s = _plain(topic.get("subject", ""))
        for key, words in SUBJECT_WORDS.items():
            if s == key or any(len(w) > 2 and _plain(w) in s for w in words):
                return key
        return None

    def _parse(self, text: str) -> dict:
        """Pull topics / mistakes / game / count out of one sentence."""
        out = {"topics": [], "mistakes": False, "subject": None, "game": None, "count": None}
        if not text:
            return out
        topics = self._all_topics()
        ids = {t.get("id") for t in topics}
        if any(_has(text, w) for w in MISTAKE_WORDS):
            out["mistakes"] = True
        for tid, words in TOPIC_WORDS.items():
            if tid in ids and any(_has(text, w) for w in words):
                out["topics"].append(tid)
        for t in topics:   # exact names/ids from the site (new topics too)
            if t.get("id") not in out["topics"] and (_has(text, t.get("name", "")) or _has(text, t.get("id", ""))):
                out["topics"].append(t["id"])
        for key, words in SUBJECT_WORDS.items():
            if any(_has(text, w) for w in words):
                out["subject"] = key
                break
        if out["subject"] and not out["topics"]:
            out["topics"] = [t["id"] for t in topics if self._subject_of(t) == out["subject"]]
        out["game"] = self._pick_game(text)
        out["count"] = self._pick_count(text, strict=True)
        return out

    def _ai_pick_topics(self, text: str) -> list:
        """Unclear words ("het ding met de longen") -> let the AI map it to topic ids."""
        topics = self._all_topics()
        if not topics:
            return []
        listing = "\n".join(f"- {t['id']}: {t.get('name')} ({t.get('subject')})" for t in topics)
        try:
            raw = brain._chat([{"role": "system", "content": "Je koppelt een gesproken zin aan onderwerpen. Antwoord alleen JSON."},
                               {"role": "user", "content": f"Onderwerpen:\n{listing}\nLeerling zei: \"{text}\"\n"
                                                           'Welke id\'s bedoelt hij? {"ids": ["..."]} (leeg als niets past)'}],
                              max_tokens=80, temperature=0)
            ids = json.loads(re.search(r"\{.*\}", raw, re.S).group(0)).get("ids") or []
        except Exception:
            return []
        valid = {t["id"] for t in topics}
        return [i for i in ids if i in valid]

    @staticmethod
    def _pick_game(text: str):
        n = _plain(text)
        if re.search(r"\b(kahoot|kahut|ka hoot|cahoot|meerkeuze)\b", n):
            return "kahoot"
        if re.search(r"\b(mix|mixed|gemengd|mics|miks)\b", n):
            return "mix"
        if re.search(r"\b(typ|type|typen|taip|open vragen|open)\b", n):
            return "typ"
        return None

    @staticmethod
    def _pick_count(text: str, strict: bool = False):
        """strict: only when clearly about a number of questions (inside a longer sentence)."""
        n = _plain(text)
        if re.search(r"\btot ik (stop|klaar)|\boneindig|\bonbeperkt|\baltijd door|\bzonder einde", n):
            return 0
        if not strict and _wants_stop(n):
            return 0
        m = re.search(r"\b(\d{1,2})\b(\s*vragen|\s*vraag)?", n)
        if m and (not strict or m.group(2)):
            return max(1, min(60, int(m.group(1))))
        for w, v in sorted(NUMBERS.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{w}\b", n) and (not strict or re.search(rf"\b{w} vragen\b", n)):
                return v
        return None

    def _apply(self, p: dict):
        if p["mistakes"]:
            self.use_mistakes = True
            self.label_text = "je fouten"
        if p["topics"]:
            self.topic_ids = p["topics"]
            names = [t.get("name", t["id"]) for t in self._all_topics() if t["id"] in self.topic_ids]
            if not self.use_mistakes:
                self.label_text = " en ".join(names) if len(names) <= 3 else f"{len(names)} onderwerpen"
        elif p["subject"] and not self._all_topics():
            self.fallback_subject = p["subject"]
            self.label_text = {"nw": "natuurwetenschappen", "hb": "historisch bewustzijn", "frans": "Frans"}[p["subject"]]
        if p["game"]:
            self.game = p["game"]
        if p["count"] is not None:
            self.total = p["count"] or None
            self.count_set = True

    def _have_selection(self) -> bool:
        return bool(self.topic_ids or self.use_mistakes or self.fallback_subject)

    def _next_prompt(self) -> str:
        if not self._have_selection():
            self.step = "pick"
            return "Wat wil je studeren? Bijvoorbeeld NW, Frans, HB, of mijn fouten."
        if not self.game:
            self.step = "game"
            return f"{self.label_text[:1].upper() + self.label_text[1:]}, top. Welk spel? Quiz mix, quiz typ of quiz kahoot?"
        if not self.count_set:
            self.step = "count"
            return "Hoeveel vragen wil je? Zeg een getal, of tot ik stop zeg."
        return self._begin()

    # ================================================================ questions
    def _build_pool(self):
        pool = []
        topics = {t["id"]: t for t in self._all_topics()}
        if self.use_mistakes:
            for m in storm_study.mistakes():
                if self.topic_ids and m.get("topic") not in self.topic_ids:
                    continue
                prompt = re.sub(r"^\s*typ\b", "Zeg", m.get("prompt", ""), flags=re.I)
                t = topics.get(m.get("topic"), {})
                pool.append({"q": prompt, "a": m.get("answer", ""), "topic": m.get("topic"), "key": m.get("key"),
                             "lang": t.get("lang"), "src": "mistake"})
        else:
            for tid in self.topic_ids:
                t = topics.get(tid)
                if not t:
                    continue
                for it in t.get("items") or []:
                    if it.get("q") and it.get("a"):
                        pool.append({"q": it["q"], "a": it["a"], "options": it.get("options"), "topic": tid,
                                     "lang": t.get("lang"), "src": "item"})
                for o in t.get("orders") or []:
                    steps = [s for s in o.get("steps") or [] if s]
                    for i in range(len(steps) - 1):
                        pool.append({"q": f"{o.get('title', 'De volgorde')}: wat komt na {steps[i]}?", "a": steps[i + 1],
                                     "topic": tid, "lang": t.get("lang"), "src": "order", "steps": steps, "prev": steps[i]})
        random.shuffle(pool)
        self.pool = pool

    def _wrong_answers(self, q: dict, k: int = 3) -> list:
        if q.get("src") == "order":
            others = [s for s in q["steps"] if _core(s) not in (_core(q["a"]), _core(q.get("prev", "")))]
        else:
            src = []
            for t in self._all_topics():
                if t["id"] == q.get("topic"):
                    src = [it.get("a") for it in t.get("items") or [] if it.get("a")]
            if not src:
                src = [m.get("answer") for m in storm_study.mistakes() if m.get("answer")]
            others = [a for a in src if _core(a) != _core(q["a"])]
        others = list(dict.fromkeys(others))
        random.shuffle(others)
        return others[:k]

    def _dress(self, q: dict) -> dict:
        """Choose how to ask this question (kahoot / open / juist-fout)."""
        q = dict(q)
        kind = {"kahoot": "kahoot", "typ": "open"}.get(self.game, "open")
        if self.game == "mix":
            kind = random.choice(["kahoot", "open", "open", "juistfout"])
        if kind == "kahoot":
            opts = [o for o in (q.get("options") or []) if o]
            if len(opts) < 4 or not any(_core(o) == _core(q["a"]) for o in opts):
                wrong = self._wrong_answers(q)
                opts = [q["a"]] + wrong if len(wrong) >= 2 else []
            if opts:
                random.shuffle(opts)
                q["options"] = opts[:4]
                if not any(_core(o) == _core(q["a"]) for o in q["options"]):
                    q["options"][0] = q["a"]
                    random.shuffle(q["options"])
            else:
                kind = "open"
        if kind == "juistfout":
            wrong = self._wrong_answers(q, 1)
            if wrong:
                q["shown"] = random.choice([q["a"], wrong[0]])
                q["truth"] = _core(q["shown"]) == _core(q["a"])
            else:
                kind = "open"
        q["kind"] = kind
        return q

    def _llm_questions(self, k: int = 5) -> list:
        """Fallback without Storm Study: AI questions from the bundled leerstof."""
        files = {"nw": "nw.txt", "hb": "hb.txt", "frans": "frans.txt"}
        material = ""
        if self.fallback_subject in files:
            with open(os.path.join(HERE, files[self.fallback_subject]), encoding="utf-8") as f:
                material = f.read()[:12000]
        try:
            raw = brain._chat([{"role": "system", "content": "Je maakt quizvragen. Antwoord alleen met een JSON-lijst."},
                               {"role": "user", "content":
                                f"Maak {k} korte quizvragen (om voor te lezen) uit deze leerstof:\n<<<\n{material}\n>>>\n"
                                'Formaat: [{"q": "...", "a": "<kort antwoord>"}]'}], max_tokens=1500, temperature=0.8)
            items = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        except Exception:
            return []
        lang = "fr" if self.fallback_subject == "frans" else None
        return [{"q": i["q"], "a": i["a"], "topic": None, "lang": lang, "src": "ai"} for i in items
                if isinstance(i, dict) and i.get("q") and i.get("a")]

    def _next_question(self):
        for _ in range(2):
            if not self.pool:
                if self.fallback_subject:
                    self.pool = self._llm_questions()
                elif self.total is None:          # "until stop": go round again
                    self.asked_keys.clear()
                    self._build_pool()
            while self.pool:
                q = self.pool.pop(0)
                key = _core(q["q"]) + "|" + _core(q["a"])
                if key in self.asked_keys:
                    continue
                self.asked_keys.add(key)
                return self._dress(q)
        return None

    def _say(self, txt: str, q: dict) -> str:
        return fr(txt) if q.get("lang") == "fr" else txt

    def _ask(self) -> str:
        q = self._next_question()
        if not q:
            self.active = False
            return "Dat waren alle vragen! " + self._summary(prefix="")
        self.current = q
        self.n += 1
        self.asked_at = time.time()
        head = f"Vraag {self.n}" + (f" van {self.total}" if self.total else "") + ". "
        if q["kind"] == "kahoot":
            opts = ". ".join(f"{'ABCD'[i]}: {self._say(o, q)}" for i, o in enumerate(q["options"]))
            return f"{head}{q['q']} {opts}."
        if q["kind"] == "juistfout":
            return f"{head}Juist of fout? {q['q']} Antwoord: {self._say(q['shown'], q)}."
        return f"{head}{q['q']}"

    def _begin(self) -> str:
        self.step = "quiz"
        if self.use_mistakes and not storm_study.mistakes():
            self.use_mistakes = False
            self.topic_ids = []
            self.step = "pick"
            return "Je hebt geen open fouten, goed bezig! Wat wil je dan studeren?"
        if not self.fallback_subject:
            self._build_pool()
            if not self.pool:
                self.step = "pick"
                self.topic_ids = []
                return "Daar vond ik geen vragen voor. Zeg update study mode, of kies een ander onderwerp."
            if self.total and self.total > len(self.pool):
                self.total = len(self.pool)
        intro = f"{self.total} {'vraag' if self.total == 1 else 'vragen'} over {self.label_text}. " if self.total else f"We oefenen {self.label_text} tot je stop zegt. "
        return intro + "Daar gaan we! " + self._ask()

    # ================================================================ checking
    def _match(self, said: str, answer: str) -> bool:
        s = _core(said)
        if not s or not _core(answer):
            return False
        pieces = [answer, re.sub(r"\(.*?\)", " ", answer)] + re.findall(r"\((.*?)\)", answer)
        alts = []
        for piece in pieces:   # "luchtpijptakken (bronchiën)", "neusholte of mondholte", "a / b"
            alts += [_core(x) for x in re.split(r"\s*(?:/|;|,|\bof\b|\bou\b)\s*", piece) if _core(x)]
        alts = list(dict.fromkeys(alts + [_core(answer)]))
        for alt in alts:
            if s == alt or (len(alt) >= 3 and re.search(rf"\b{re.escape(alt)}\b", s)):
                return True
            if difflib.SequenceMatcher(None, s, alt).ratio() >= 0.82:
                return True
            words, n = s.split(), len(alt.split())
            for i in range(len(words) - n + 1):     # answer said inside a longer sentence
                if difflib.SequenceMatcher(None, " ".join(words[i:i + n]), alt).ratio() >= 0.85:
                    return True
        return False

    def _judge(self, q: dict, said: str) -> bool:
        try:
            verdict = brain._chat([
                {"role": "system", "content": "Je verbetert soepel een gesproken antwoord van een leerling. "
                                              "Hoofdletters, lidwoorden (de/het/le/la) en kleine uitspraak- of "
                                              "spraakherkenningsfouten tellen niet. Antwoord alleen JSON."},
                {"role": "user", "content": f"Vraag: {q['q']}\nJuist antwoord: {q['a']}\nLeerling zei: {said}\n"
                                            '{"correct": true/false}'}], max_tokens=40, temperature=0)
        except Exception:
            return False
        return bool(re.search(r'"correct"\s*:\s*true', verdict, re.I))

    def _check(self, said: str) -> bool:
        q = self.current
        n = _plain(said)
        if q["kind"] == "kahoot":
            words = n.split()
            if words and words[0] in LETTERS and LETTERS[words[0]] < len(q["options"]) and len(words) <= 3:
                return _core(q["options"][LETTERS[words[0]]]) == _core(q["a"])
            m = re.search(r"\b(?:antwoord|optie|letter)\s+([abcd])\b", n)
            if m and "abcd".index(m.group(1)) < len(q["options"]):
                return _core(q["options"]["abcd".index(m.group(1))]) == _core(q["a"])
            best = max((difflib.SequenceMatcher(None, _core(said), _core(o)).ratio(), o) for o in q["options"])
            if best[0] >= 0.75:
                return _core(best[1]) == _core(q["a"])
            return self._match(said, q["a"]) or self._judge(q, said)
        if q["kind"] == "juistfout":
            yes = re.search(r"\b(juist|waar|klopt|correct|ja|goed)\b", n)
            no = re.search(r"\b(fout|onjuist|nee|niet waar|klopt niet)\b", n)
            if yes or no:
                return bool(yes and not no) == q["truth"]
            return self._judge({"q": f"Juist of fout: {q['q']} -> {q['shown']}", "a": "juist" if q["truth"] else "fout"}, said)
        return self._match(said, q["a"]) or self._judge(q, said)

    def _feedback(self, said: str) -> str:
        q = self.current
        right = self._check(said)
        self.answered += 1
        if q.get("topic"):
            body = {"action": "answer", "topic": q["topic"], "question": q["q"], "answer": said,
                    "expected": q["a"], "correct": right}
            if q.get("key"):
                body["key"] = q["key"]
            storm_study.post_async(body)
        if right:
            self.correct += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
            msg = random.choice(["Juist!", "Correct!", "Goed zo!", "Helemaal juist!", "Top!"])
            if q.get("kind") == "open" and _core(said) != _core(q["a"]):
                msg += f" Precies: {self._say(q['a'], q)}."
            if self.streak % 5 == 0:
                storm_study.post_async({"action": "points", "points": 25, "reason": f"{self.streak} juist na elkaar"})
                msg += f" {self.streak} na elkaar, bonus van 25 punten!"
        else:
            self.streak = 0
            msg = f"Helaas. Het juiste antwoord is: {self._say(q['a'], q)}."
        return msg

    def _summary(self, prefix: str = "Studiemodus gestopt. ") -> str:
        if not self.answered:
            return (prefix + "Tot de volgende keer!").strip()
        r = self.correct / self.answered
        cheer = " Topscore!" if r >= 0.9 else " Goed bezig!" if r >= 0.6 else " Nog even oefenen, je kan het!"
        time.sleep(0.4)      # let the last answer reach Storm Study first
        pts = storm_study.points()
        extra = f" Je staat nu op {pts} punten op Storm Study." if pts is not None else ""
        if storm_study.queued():
            extra += " Een paar antwoorden stuur ik later door, Storm Study was niet bereikbaar."
        return f"{prefix}Je had {self.correct} van de {self.answered} juist.{cheer}{extra}"

    # ================================================================ conversation
    def start(self, text: str = "") -> str:
        self.__init__()
        self.active = True
        if storm_study.enabled():
            storm_study.flush_queue()
        self._apply(self._parse(text))
        if not self._have_selection():
            self.step = "pick"
            return "Studiemodus aan! Wat wil je studeren? NW, Frans, HB, of mijn fouten?"
        return "Studiemodus aan. " + self._next_prompt()

    def stop(self) -> str:
        msg = self._summary()
        self.active = False
        return msg

    def silence(self) -> str:
        self.silent_turns += 1
        if self.silent_turns >= 2:
            self.active = False
            return self._summary() + " Ik hoorde niets meer, dus ik stop."
        if self.step == "quiz" and self.current:
            return "Ik hoorde je niet. Wat is je antwoord? Of zeg stop."
        return "Ik hoorde je niet. Zeg het nog eens?"

    def handle(self, text: str) -> str:
        self.silent_turns = 0
        if (self.step != "count" and _wants_stop(text)
                and not (self.step == "quiz" and self.current and self._match(text, self.current["a"]))):
            return self.stop()
        if self.step == "pick":
            p = self._parse(text)
            if not (p["topics"] or p["mistakes"] or p["subject"]):
                p["topics"] = self._ai_pick_topics(text)
            self._apply(p)
            if not self._have_selection():
                return "Dat vond ik niet. Zeg bijvoorbeeld NW, Frans, HB, ademhaling, of mijn fouten."
            return self._next_prompt()
        if self.step == "game":
            g = self._pick_game(text)
            if not g:
                return "Kies quiz mix, quiz typ of quiz kahoot."
            self.game = g
            c = self._pick_count(text, strict=True)
            if c is not None:
                self.total, self.count_set = c or None, True
            return self._next_prompt()
        if self.step == "count":
            c = self._pick_count(text)
            if c is None:
                return "Hoeveel vragen? Bijvoorbeeld tien, of tot ik stop zeg."
            self.total, self.count_set = c or None, True
            return self._begin()
        if self.step == "quiz" and self.current:
            fb = self._feedback(text)
            if self.total and self.answered >= self.total:
                self.active = False
                return fb + " " + self._summary(prefix="Klaar! ")
            return fb + " " + self._ask()
        self.active = False
        return "Studiemodus gestopt."


session = Session()


def clean(text: str) -> str:
    """Text without voice markers (for the history on the page)."""
    return re.sub(r"\[\[fr:(.*?)\]\]", r"\1", text or "")
