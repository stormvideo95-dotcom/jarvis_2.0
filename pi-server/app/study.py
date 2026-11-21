"""Study mode: a spoken quiz from Storm's own study material (app/leerstof/*.txt).

Flow:  "Jarvis, start studiemodus"
  -> Wat wil je studeren?            "NW"
  -> Welk spel?                      "quiz kahoot" | "quiz type" | "quiz mix"
  -> Hoeveel vragen?                 "10" | "tot ik stop zeg"
  -> questions... (Jarvis listens by itself after every question; say "stop" to end)

Game types
  kahoot : 4 options A-D, points (faster = more) and a streak bonus
  type   : open question, answer in your own words
  mix    : kahoot + open + juist/fout, mixed
"""
import json
import os
import random
import re
import time
import unicodedata

from . import brain

HERE = os.path.join(os.path.dirname(__file__), "leerstof")

SUBJECTS = {
    "nw": ("natuurwetenschappen", "nw.txt",
           ("nw", "n w", "natuurwetenschap", "wetenschap", "biologie", "bio", "cel", "ademhaling", "longen", "hart", "bloed", "transport")),
    "hb": ("historisch bewustzijn", "hb.txt",
           ("hb", "h b", "historisch", "geschiedenis", "domein", "bron", "labster")),
    "frans": ("Frans", "frans.txt",
              ("frans", "francais", "français", "french", "le corps", "corps", "sens", "expression")),
}
STOP = ("stop", "stoppen", "genoeg", "einde", "klaar", "hou op", "ik stop")
NUMBERS = {"een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8,
           "negen": 9, "tien": 10, "elf": 11, "twaalf": 12, "dertien": 13, "veertien": 14, "vijftien": 15,
           "twintig": 20, "dertig": 30}
LETTER_WORDS = {"a": "A", "aa": "A", "b": "B", "be": "B", "bee": "B", "c": "C", "ce": "C", "cee": "C", "see": "C",
                "d": "D", "dee": "D"}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def _wants_stop(text: str) -> bool:
    n = _norm(text)
    return any(re.search(rf"\b{re.escape(w)}\b", n) for w in STOP)


class Session:
    def __init__(self):
        self.active = False
        self.step = None            # subject | game | count | quiz
        self.subject = None         # key in SUBJECTS or free text
        self.focus = ""             # e.g. "de cel"
        self.game = None
        self.total = None           # None = until "stop"
        self.questions = []
        self.asked = []
        self.current = None
        self.asked_at = 0.0
        self.n = 0
        self.answered = 0
        self.correct = 0
        self.points = 0
        self.streak = 0
        self.silent_turns = 0

    # ---- helpers ------------------------------------------------------------
    def label(self) -> str:
        if self.subject in SUBJECTS:
            return SUBJECTS[self.subject][0]
        return self.subject or "?"

    def _material(self) -> str:
        if self.subject in SUBJECTS:
            with open(os.path.join(HERE, SUBJECTS[self.subject][1]), encoding="utf-8") as f:
                return f.read()
        return ""

    def _pick_subject(self, text: str) -> bool:
        n = _norm(text)
        if not n:
            return False
        for key, (_, _, words) in SUBJECTS.items():
            if any(re.search(rf"\b{re.escape(_norm(w))}\b", n) for w in words):
                self.subject = key
                topic = re.sub(r"\b(nw|hb|frans|ik wil|studeren|leren|over|graag|aub)\b", " ", n)
                self.focus = re.sub(r"\s+", " ", topic).strip() if len(topic.split()) >= 2 else ""
                return True
        self.subject = text.strip()     # something else: general knowledge
        return True

    @staticmethod
    def _pick_game(text: str):
        n = _norm(text)
        if "kahoot" in n or "kahut" in n or "ka hoot" in n:
            return "kahoot"
        if "mix" in n or "gemengd" in n or "mics" in n:
            return "mix"
        if "type" in n or "typ" in n or "open" in n or "taip" in n:
            return "type"
        return None

    @staticmethod
    def _pick_count(text: str):
        n = _norm(text)
        if _wants_stop(n) or "oneindig" in n or "altijd" in n or "tot ik" in n:
            return 0
        m = re.search(r"\b(\d{1,2})\b", n)
        if m:
            return max(1, min(50, int(m.group(1))))
        for w, v in NUMBERS.items():
            if re.search(rf"\b{w}\b", n):
                return v
        return None

    # ---- questions ------------------------------------------------------------
    def _make_questions(self, k: int = 5):
        kinds = {"kahoot": "kahoot", "type": "open", "mix": "kahoot, open en juistfout door elkaar"}[self.game]
        material = self._material()
        src = ("Gebruik ALLEEN deze leerstof:\n<<<\n" + material[:12000] + "\n>>>\n") if material else \
              f"Vak: {self.label()}. Niveau: eerste graad secundair onderwijs in Vlaanderen.\n"
        focus = f"Focus vooral op: {self.focus}.\n" if self.focus else ""
        avoid = ("Stel deze vragen NIET opnieuw: " + " | ".join(q["q"] for q in self.asked[-25:]) + "\n") if self.asked else ""
        prompt = (
            f"Maak {k} korte quizvragen in het Nederlands (Frans mag bij het vak Frans) voor een leerling, type: {kinds}.\n"
            + src + focus + avoid +
            "Regels: vragen worden VOORGELEZEN, dus kort en duidelijk, geen tabellen of afkortingen.\n"
            "Geef ALLEEN een JSON-lijst, elk item:\n"
            '{"kind": "kahoot", "q": "...", "options": ["...","...","...","..."], "answer": "<exact juiste optie>"}\n'
            '{"kind": "open", "q": "...", "answer": "<kort antwoord>", "accept": ["<ander goed antwoord>"]}\n'
            '{"kind": "juistfout", "q": "<stelling>", "answer": "juist" of "fout"}\n'
        )
        raw = brain._chat([{"role": "system", "content": "Je maakt quizvragen. Antwoord alleen met JSON."},
                           {"role": "user", "content": prompt}], max_tokens=1800, temperature=0.8)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
        m = re.search(r"\[.*\]", raw, re.S)
        items = []
        try:
            items = json.loads(m.group(0)) if m else []
        except ValueError:
            pass
        seen = {_norm(q["q"]) for q in self.asked + self.questions}
        for it in items:
            if not isinstance(it, dict) or not it.get("q") or not it.get("answer"):
                continue
            if _norm(it["q"]) in seen:      # never the same question twice
                continue
            seen.add(_norm(it["q"]))
            kind = it.get("kind", "open")
            if kind == "kahoot":
                opts = [str(o) for o in (it.get("options") or [])][:4]
                if len(opts) < 2 or str(it["answer"]) not in opts:
                    continue
                random.shuffle(opts)
                it["options"] = opts
            if self.game == "kahoot" and kind != "kahoot":
                continue
            if self.game == "type" and kind != "open":
                continue
            self.questions.append(it)

    def _say_question(self) -> str:
        if not self.questions:
            self._make_questions()
        if not self.questions:
            self.active = False
            return "Sorry, ik kon geen vragen maken. Probeer het straks opnieuw."
        q = self.questions.pop(0)
        self.current = q
        self.asked.append(q)
        self.n += 1
        self.asked_at = time.time()
        head = f"Vraag {self.n}" + (f" van {self.total}" if self.total else "") + ". "
        if q["kind"] == "kahoot":
            opts = ". ".join(f"{'ABCD'[i]}: {o}" for i, o in enumerate(q["options"]))
            return f"{head}{q['q']} {opts}."
        if q["kind"] == "juistfout":
            return f"{head}Juist of fout? {q['q']}"
        return f"{head}{q['q']}"

    # ---- checking ---------------------------------------------------------------
    def _check(self, text: str):
        q = self.current
        n = _norm(text)
        ans = _norm(str(q["answer"]))
        if q["kind"] == "kahoot":
            for i, o in enumerate(q["options"]):
                if _norm(o) and _norm(o) in n:
                    return _norm(o) == ans
            first = n.split()[:3]
            for w in first:
                if w in LETTER_WORDS:
                    letter = LETTER_WORDS[w]
                    idx = "ABCD".index(letter)
                    if idx < len(q["options"]):
                        return _norm(q["options"][idx]) == ans
            m = re.search(r"\b(?:antwoord|optie|letter)\s+([abcd])\b", n)
            if m:
                return _norm(q["options"]["abcd".index(m.group(1))]) == ans
        elif q["kind"] == "juistfout":
            said_true = re.search(r"\b(juist|waar|klopt|correct|ja)\b", n)
            said_false = re.search(r"\b(fout|niet waar|onjuist|nee|false)\b", n)
            if said_true or said_false:
                return bool(said_false) == (ans == "fout")
        else:
            accepted = [ans] + [_norm(a) for a in (q.get("accept") or [])]
            if any(a and a in n for a in accepted):
                return True
        # unclear: let the AI judge (short, one call)
        verdict = brain._chat([{"role": "system", "content": "Je verbetert een antwoord van een leerling. Antwoord alleen JSON."},
                               {"role": "user", "content":
                                f"Vraag: {q['q']}\nOpties: {q.get('options')}\nJuist antwoord: {q['answer']}\n"
                                f"Leerling zei (spraakherkenning, kan fouten bevatten): {text}\n"
                                'Is het juist? {"correct": true/false}'}], max_tokens=60, temperature=0)
        return '"correct": true' in verdict.replace("True", "true").lower() or '"correct":true' in verdict.lower()

    def _answer_feedback(self, text: str) -> str:
        q = self.current
        took = time.time() - self.asked_at
        right = self._check(text)
        self.answered += 1
        if right:
            self.correct += 1
            self.streak += 1
            msg = random.choice(["Juist!", "Correct!", "Goed zo!", "Helemaal juist!"])
            if self.game == "kahoot" or q["kind"] == "kahoot":
                pts = max(500, int(1000 - max(0.0, took - 6) * 40))
                bonus = 100 * (self.streak - 1) if self.streak > 1 else 0
                self.points += pts + bonus
                msg += f" Plus {pts + bonus} punten" + (f", streak van {self.streak}!" if self.streak > 2 else ".")
        else:
            self.streak = 0
            msg = f"Helaas, het juiste antwoord was: {q['answer']}."
        return msg

    def _summary(self) -> str:
        done = self.answered
        if done == 0:
            return "Studiemodus gestopt."
        pts = f" en {self.points} punten" if self.points else ""
        score = f"Je had {self.correct} van de {done} juist{pts}." if done else ""
        cheer = ""
        if done:
            r = self.correct / done
            cheer = " Topscore!" if r >= 0.9 else " Goed bezig!" if r >= 0.6 else " Nog even oefenen, je kan het!"
        return f"Studiemodus gestopt. {score}{cheer}".strip()

    # ---- conversation -------------------------------------------------------------
    def start(self, subject_hint: str = "") -> str:
        self.__init__()
        self.active = True
        if subject_hint and self._pick_subject(subject_hint):
            self.step = "game"
            return f"Studiemodus aan voor {self.label()}. Welk spel wil je spelen? Quiz mix, quiz type of quiz kahoot?"
        self.step = "subject"
        return "Studiemodus aan! Wat wil je studeren? Bijvoorbeeld NW, HB of Frans."

    def stop(self) -> str:
        msg = self._summary()
        self.active = False
        return msg

    def silence(self) -> str | None:
        """No answer heard. Returns what to say, or None to end quietly."""
        self.silent_turns += 1
        if self.silent_turns >= 2:
            self.active = False
            return self._summary() + " Ik hoorde niets meer, dus ik stop."
        if self.step == "quiz" and self.current:
            return "Ik hoorde je niet. Wat is je antwoord? Of zeg stop."
        return "Ik hoorde je niet. Zeg het nog eens?"

    def handle(self, text: str) -> str:
        self.silent_turns = 0
        if _wants_stop(text) and self.step != "count":
            return self.stop()
        if self.step == "subject":
            self._pick_subject(text)
            self.step = "game"
            return f"{self.label().capitalize()}, top. Welk spel wil je spelen? Quiz mix, quiz type of quiz kahoot?"
        if self.step == "game":
            g = self._pick_game(text)
            if not g:
                return "Dat verstond ik niet. Kies quiz mix, quiz type of quiz kahoot."
            self.game = g
            self.step = "count"
            return "Hoeveel vragen wil je? Zeg een getal, of zeg tot ik stop zeg."
        if self.step == "count":
            c = self._pick_count(text)
            if c is None:
                return "Hoeveel vragen? Bijvoorbeeld tien, of tot ik stop zeg."
            self.total = c or None
            self.step = "quiz"
            self._make_questions()
            intro = f"Oké, {c} vragen. " if c else "Oké, we gaan door tot je stop zegt. "
            return intro + "Daar gaan we! " + self._say_question()
        if self.step == "quiz" and self.current:
            fb = self._answer_feedback(text)
            if self.total and self.n >= self.total:
                self.active = False
                return fb + " " + self._summary().replace("Studiemodus gestopt. ", "Klaar! ")
            if len(self.questions) < 2:
                self._make_questions()
            return fb + " " + self._say_question()
        self.active = False
        return "Studiemodus gestopt."


session = Session()
