import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .lexer import (CONNECTOR_WORDS, DETERMINERS, DICTATION_VERBS, VERB_SYNONYMS, Lexer, _TOKEN_RE)
from .registry import APP_INDEX, KEY_ALIASES, WEBSITES
from .speech import normalize_transcript

SPELLED = re.compile(r"\b((?:[A-Za-z]\.\s*){2,})")
FILLERS = re.compile(r"(?<![\w'])(?:u+m+|u+h+|e+r+m*|a+h+|h+m+|m+h*m+)(?![\w'])[,.]?\s*", re.I)
CLAUSE = r"(?:^|(?<=\band )|(?<=\bthen )|(?<=, )|(?<=\. ))"

POLITE_RULES = [
    ("leading filler", r"^(?:(?:hey|hi|hello|ok(?:ay)?|alright|all right|so|now|then|well|basically|right|first(?: of all)?|and|also|just|kindly|actually)\b[\s,]*)+", ""),
    ("sequence filler", r"(\b(?:and|then)\s+|,\s*)(?:so|now|basically|just|also|next|after that|finally)\b[\s,]*", r"\1"),
    ("request phrase", r"\b(?:can|could|would|will) you(?: please)?(?: kindly)?\s+", ""),
    ("want phrase", r"\b(?:i (?:want|would like|need|wanna)|i'd like|let's|lets)\s+(?:you\s+)?(?:to\s+)?", ""),
    ("please", r"\bplease\b[\s,]*", ""),
    ("for me", r"\s*\bfor me\b", ""),
    ("thanks", r"[\s,]*\b(?:thanks|thank you)\b.*$", ""),
    ("repeated phrase", r"\b(\w+(?:\s+\w+){1,2})\s+\1\b", r"\1"),
    ("softener", r"\s*\b(?:a bit|a little(?: bit)?|quickly|right now)\b", ""),
]

FILE_EXT = {"text": ".txt", "txt": ".txt", "python": ".py", "html": ".html", "web": ".html", "csv": ".csv",
            "markdown": ".md", "json": ".json", "javascript": ".js", "java": ".java", "css": ".css", "word": ".docx"}


def _typed_file(m):
    kind, name = m.group(1).lower(), m.group(2).strip()
    if "." in name:
        return name
    return name.replace(" ", "_") + FILE_EXT[kind]


NAME = r"([A-Za-z][\w.'-]*(?:\s+[A-Za-z][\w.'-]*){0,2}?)"
WA = r"(?:whats\s?app|whatsapp)"
SAYING = r"(?:saying|that says|and say|and send|and tell (?:him|her|them)|and type|and write|with the message|message)"

WHATSAPP_RULES = [
    ("whatsapp open chat", CLAUSE + r"(?:open|go to|show|start|bring up)\s+(?:my\s+|the\s+)?" + WA + r"\s+chat\s+(?:with|of|for)\s+" + NAME + r"(?:\s+" + SAYING + r"\s+(?:that\s+)?(.+))?$",
     lambda m: f"chat with {m.group(1)}" + (f" saying {m.group(2)}" if m.group(2) else "")),
    ("whatsapp chat on", CLAUSE + r"(?:open|go to|show|start)\s+(?:the\s+|a\s+)?chat\s+(?:with|of|for)\s+" + NAME + r"\s+(?:on|in)\s+" + WA + r"(?:\s+" + SAYING + r"\s+(?:that\s+)?(.+))?$",
     lambda m: f"chat with {m.group(1)}" + (f" saying {m.group(2)}" if m.group(2) else "")),
    ("whatsapp possessive", CLAUSE + r"(?:open|go to|show)\s+" + NAME + r"(?:'s|s)?\s+chat\s+(?:on|in)\s+" + WA + r"$",
     lambda m: f"chat with {m.group(1)}"),
    ("whatsapp send to on", CLAUSE + r"(?:send|whatsapp|message|text|ping)\s+(?:a\s+)?(?:message\s+|msg\s+)?(?:to\s+)?" + NAME + r"\s+(?:on|in|via|through)\s+" + WA + r"\s+(?:saying|that|telling (?:him|her|them))?\s*:?\s*(.+)$",
     lambda m: f"chat with {m.group(1)} saying {m.group(2)}"),
    ("whatsapp send text to", CLAUSE + r"(?:send|write)\s+(.+?)\s+to\s+" + NAME + r"\s+(?:on|in|via|through)\s+" + WA + r"$",
     lambda m: f"chat with {m.group(2)} saying {m.group(1)}"),
    ("whatsapp tell", CLAUSE + r"tell\s+" + NAME + r"\s+(?:on|in|via)\s+" + WA + r"\s+(?:that\s+)?(.+)$",
     lambda m: f"chat with {m.group(1)} saying {m.group(2)}"),
    ("whatsapp message saying", CLAUSE + r"(?:whatsapp|message|text|ping)\s+" + NAME + r"\s+(?:saying|that)\s+(.+)$",
     lambda m: f"chat with {m.group(1)} saying {m.group(2)}"),
    ("whatsapp chat with on", CLAUSE + r"chat\s+with\s+" + NAME + r"\s+(?:on|in)\s+" + WA + r"$",
     lambda m: f"chat with {m.group(1)}"),
    ("whatsapp verb", CLAUSE + r"(?:whatsapp|message)\s+" + NAME + r"$",
     lambda m: f"chat with {m.group(1)}"),
]

REWRITE_RULES = WHATSAPP_RULES + [
    ("typed file name", r"\b(text|txt|python|html|web|csv|markdown|json|javascript|java|css)\s+(?:file|script|program)\s+(?:called|named|with the name)\s+([\w\-]+(?:\.\w+)?(?:\s+(?!and\b|then\b)[\w\-]+)?)", _typed_file),
    ("screenshot split", r"\bscreen\s*(?:shot|sort|shoot|short|sot|shut)s?\b", "screenshot"),
    ("capture screen", r"\b(?:grab|snap|capture|get|click|take)\s+(?:a\s+|the\s+)?(?:screenshot|screen|snapshot|snap)\b(?:\s+of\s+(?:the\s+)?screen)?", "take a screenshot"),
    ("screenshot this", r"\bscreenshot\s+(?:this|that|it|the screen)\b", "take a screenshot"),
    ("put it in", r"\b(?:put|place|drop)\s+(?:it|this|that)\s+(?:in|into|inside|on)\s+", "paste it into "),
    ("open synonyms", r"\b(?:start up|bring up|fire up|boot up|pull up|open up|load up|show me|launch up)\b", "open"),
    ("navigate", r"\b(?:navigate to|browse to|head to|head over to)\b", "go to"),
    ("switch synonyms", r"\b(?:switch over to|go back to|switch back to|return to|jump to|move to|change to)\b", "switch to"),
    ("close synonyms", r"\b(?:kill|terminate|get rid of|shut(?:\s+down)?)\s+(?!down\b)(?!(?:the\s+|my\s+|this\s+)?(?:computer|pc|laptop|system|machine|windows)\b)", "close "),
    ("media pause", r"^(?:pause|stop|hold)\s+(?:the\s+|this\s+)?(?:song|video|music|playback|youtube|track)$|^pause$", "press playpause"),
    ("media resume", r"^(?:resume|continue|unpause|play)\s+(?:the\s+|this\s+)?(?:song|video|music|playback|track)(?:\s+again)?$|^resume$", "press playpause"),
    ("media next", r"^(?:(?:play\s+)?(?:the\s+)?next|skip)(?:\s+(?:the|this))?\s+(?:song|video|track)$|^skip$|^next$", "press nexttrack"),
    ("media previous", r"^(?:(?:play\s+)?(?:the\s+)?previous|last|go back to the previous)\s+(?:song|video|track)$", "press prevtrack"),
    ("youtube play", CLAUSE + r"(?:play|put on|start playing)\s+(.+?)(?:\s+(?:on|in|from)\s+youtube)?$", r"play \1"),
    ("youtube find", CLAUSE + r"\b(?:find|search|look for|look up|search for)\s+(.+?)\s+(?:on|in)\s+youtube\b", r"search youtube for \1"),
    ("youtube open and play", CLAUSE + r"(?:open|go to)\s+youtube\s+and\s+play\s+(.+)$", r"play \1"),
    ("search for misheard", r"\bsearch\s+(?:four|fore|4)\b", "search for"),
    ("google verb", CLAUSE + r"(?:google|look up|lookup|search up|find out about|search on google for|search google for|search the web for|search online for)\s+", "search for "),
    ("volume up", r"\b(?:turn up|crank up|pump up|raise|increase|boost)\s+(?:the\s+)?(?:volume|sound)\b|\bturn\s+(?:the\s+)?(?:volume|sound)\s+up\b|\bmake\s+(?:it|the\s+(?:volume|sound))\s+louder\b|\blouder\b", "volume up"),
    ("volume down", r"\b(?:turn down|lower|reduce|decrease|drop)\s+(?:the\s+)?(?:volume|sound)\b|\bturn\s+(?:the\s+)?(?:volume|sound)\s+down\b|\bmake\s+(?:it|the\s+(?:volume|sound))\s+(?:quieter|softer)\b|\b(?:quieter|softer)\b", "volume down"),
    ("mute target", r"\b(un)?mute\s+(?:the\s+)?(?:sound|audio|volume|speakers?|computer|laptop)\b", r"\1mute"),
    ("key word", r"\b(?:hit|press|tap|push)\s+(?:the\s+)?([\w+]+(?:\s+[\w+]+)?)\s+(?:key|button)s?\b", r"press \1"),
    ("save file", r"\bsave\s+(?:the|this|my)\s+(?:file|document|doc|work|changes)\b", "save"),
    ("new folder", r"\b(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:folder|directory)\b", "create folder"),
    ("window size", r"\b(minimi[sz]e|maximi[sz]e)\s+(?:this|the|current|that|it)?\s*(?:window|app)?\b", r"\1 window"),
    ("refresh", r"\b(?:refresh|reload)\b(?:\s+(?:the|this))?(?:\s+(?:page|tab|website))?", "press f5"),
    ("new tab", r"\bopen\s+(?:a\s+)?new\s+tab\b", "press control t"),
    ("new window", r"\bopen\s+(?:a\s+)?new\s+window\b", "press control n"),
    ("undo", r"\bundo\b(?:\s+(?:that|it|this|the last (?:change|thing)))?", "press control z"),
    ("redo", r"\bredo\b(?:\s+(?:that|it|this))?", "press control y"),
    ("browser back", CLAUSE + r"go back$", "press alt left"),
    ("lock", r"\block\s+(?:my\s+|the\s+|this\s+)?(?:computer|pc|laptop|screen|system|device)\b", "lock screen"),
    ("select all", r"\b(?:select|highlight)\s+(?:everything|all(?:\s+the)?\s+text|all of it|the whole thing|whole text)\b", "select all"),
    ("copy all", r"\bcopy\s+(?:everything|all(?:\s+the)?\s+text|all of it|the whole thing|all)\b", "select all and copy"),
    ("ask time", r"^(?:what(?:'s| is) the (?:current )?time(?: now)?|what time is it(?: now)?|tell me the time|current time|time now|what's the time now)\??$", "tell time"),
    ("ask date", r"^(?:what(?:'s| is) (?:the )?(?:date|day)(?: today)?|what(?:'s| is) today's date|what day is (?:it|today)(?: today)?|today's date|tell me the date|what is the date today)\??$", "tell date"),
    ("ask math", r"^(?:what(?:'s| is)|whats|how much is|tell me)\s+(.*(?:\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred)\b).*(?:\+|-|\*|/|%|\bplus\b|\bminus\b|\btimes\b|\binto\b|\bx\b|\bdivided\b|\bover\b|\bpercent\b|\bsquared\b|\bpower\b|\broot\b).*?)\??$", r"calculate \1"),
]

CORRECTION_MARKERS = [
    r"no wait", r"no no", r"no sorry", r"sorry i mean", r"sorry i meant", r"i mean", r"i meant",
    r"or rather", r"rather", r"sorry", r"wait no", r"no",
]
VERB_MARKERS = CORRECTION_MARKERS + [r"actually", r"instead"]

CONFUSIONS = {
    "verb": {"tape": "type", "tight": "type", "tie": "type", "taip": "type", "pest": "paste", "paced": "paste",
             "based": "paste", "pace": "paste", "safe": "save", "clothes": "close", "cloths": "close",
             "clause": "close", "weight": "wait", "wade": "wait", "coffee": "copy", "copie": "copy",
             "oven": "open", "often": "open", "opan": "open", "serch": "search", "surge": "search",
             "pres": "press", "prize": "press", "creat": "create", "great": "create", "delight": "delete",
             "dilute": "delete", "switched": "switch", "scroll": "scroll", "school": "scroll", "scrawl": "scroll",
             "nut": "mute", "newt": "mute", "click": "click", "lick": "click", "minimise": "minimize"},
    "key": {"inter": "enter", "enta": "enter", "tap": "tab", "tub": "tab", "escap": "escape", "space": "space",
            "spacebar": "space", "contrl": "control", "control": "control", "ault": "alt", "halt": "alt",
            "shit": "shift", "shiv": "shift", "deleted": "delete"},
    "direction": {"don": "down", "dawn": "down", "done": "down", "dhan": "down", "app": "up", "op": "up", "ap": "up",
                  "upp": "up"},
    "for": {"four": "for", "4": "for", "fore": "for", "far": "for"},
}

DIRECTION_VERBS = {"scroll", "volume"}
NEVER_CORRECT = {"what", "why", "how", "who", "when", "where", "which", "that", "this", "these", "those", "is", "are",
                 "was", "were", "can", "could", "does", "do", "did", "the", "a", "an", "it", "its", "hat", "chat",
                 "hello", "hi", "hey", "thanks", "please", "yes", "no", "ok", "okay", "i", "my", "me", "we", "you",
                 "explain", "define", "tell", "show", "give", "should", "would", "will", "shall", "have", "has"}
EXPLICIT_ONLY_VERBS = {"chat", "tell", "lock"}
QUESTION_START = re.compile(r"^(?:what|why|how|who|when|where|which|explain|define|is|are|can|does|do|should|would|will)\b", re.I)
KEY_VOCAB = set(KEY_ALIASES) | {chr(c) for c in range(ord("a"), ord("z") + 1)} | {f"f{i}" for i in range(1, 13)}


@dataclass
class Step:
    stage: str
    rule: str
    before: str
    after: str


@dataclass
class Understanding:
    original: str
    text: str
    steps: List[Step] = field(default_factory=list)
    corrections: List[Tuple[str, str]] = field(default_factory=list)
    confident: bool = True

    def changed(self):
        return self.text != self.original


def protected_spans(text):
    lexer = Lexer.__new__(Lexer)
    lexer.text = text
    matches = list(_TOKEN_RE.finditer(text))
    spans = []
    i, n = 0, len(matches)
    while i < n:
        w = lexer._word(matches[i])
        prev = lexer._word(matches[i - 1]) if i else None
        if w in VERB_SYNONYMS and VERB_SYNONYMS[w] in DICTATION_VERBS and prev not in DETERMINERS:
            k = i + 1
            while k < n and not lexer._is_boundary(matches, k) and not _is_marker_then_verb(matches, k, lexer):
                k += 1
            if k > i + 1:
                spans.append((matches[i + 1].start(), matches[k - 1].end() if k < n else len(text)))
            i = k
            continue
        if m := _QUOTE.match(text, matches[i].start()):
            spans.append((m.start(), m.end()))
        i += 1
    return spans


_QUOTE = re.compile(r"\"[^\"]*\"")


def _is_marker_then_verb(matches, k, lexer):
    for size in (3, 2, 1):
        words = [lexer._word(matches[j]) for j in range(k, min(k + size, len(matches)))]
        if len(words) < size or any(w is None for w in words):
            continue
        phrase = " ".join(words)
        if phrase in VERB_MARKERS and k + size + 1 < len(matches):
            nxt = lexer._word(matches[k + size])
            if nxt in VERB_SYNONYMS:
                return True
    return False


def _inside(pos, spans):
    return any(a <= pos < b for a, b in spans)


def apply_rules(text, rules, stage, steps):
    for name, pattern, repl in rules:
        regex = re.compile(pattern, re.I)
        spans = protected_spans(text)
        changed = False

        def sub(m):
            nonlocal changed
            if _inside(m.start(), spans):
                return m.group(0)
            changed = True
            return repl(m) if callable(repl) else m.expand(repl)

        new = regex.sub(sub, text)
        new = re.sub(r"\s+", " ", new).strip(" ,")
        if changed and new != text:
            steps.append(Step(stage, name, text, new))
            text = new
    return text


def _clause_bounds(words, idx):
    start = 0
    for j in range(idx - 1, -1, -1):
        w = words[j].lower().strip(",.")
        if w in CONNECTOR_WORDS or words[j].endswith((",", ".")):
            start = j + 1
            break
    return start


def resolve_self_corrections(text, steps):
    for _ in range(4):
        words = text.split()
        lows = [w.lower().strip(",.!?") for w in words]
        spans = protected_spans(text)
        offsets, pos = [], 0
        for w in words:
            pos = text.index(w, pos)
            offsets.append(pos)
            pos += len(w)
        found = None
        for i in range(1, len(words)):
            for marker in sorted(VERB_MARKERS, key=lambda m: -len(m.split())):
                parts = marker.split()
                if lows[i:i + len(parts)] != parts:
                    continue
                after = i + len(parts)
                if after >= len(words):
                    continue
                follows_verb = lows[after] in VERB_SYNONYMS
                in_span = _inside(offsets[i], spans)
                if follows_verb and in_span and after + 1 >= len(words):
                    continue
                if not follows_verb and (marker not in CORRECTION_MARKERS or in_span):
                    continue
                found = (i, after, follows_verb, marker)
                break
            if found:
                break
        if not found:
            return text
        i, after, follows_verb, marker = found
        start = _clause_bounds(words, i)
        rest = words[after:]
        if follows_verb:
            new_words = words[:start] + rest
        else:
            verb_idx = next((j for j in range(start, i) if lows[j] in VERB_SYNONYMS), None)
            if verb_idx is None or len(rest) > 4:
                return text
            if rest and rest[0].lower() == "not" and len(rest) > 2:
                rest = rest[2:]
            new_words = words[:verb_idx + 1] + rest
        new = " ".join(new_words).strip(" ,")
        steps.append(Step("self-correction", marker, text, new))
        text = new
    return text


def phonetic(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    for a, b in (("ph", "f"), ("ck", "k"), ("sch", "sk"), ("th", "t"), ("sh", "s"), ("ch", "k"), ("wh", "w"),
                 ("gh", ""), ("kn", "n"), ("wr", "r"), ("x", "ks"), ("q", "k"), ("z", "s"), ("v", "f")):
        w = w.replace(a, b)
    w = re.sub(r"c(?=[eiy])", "s", w).replace("c", "k")
    if not w:
        return ""
    first = "A" if w[0] in "aeiou" else w[0]
    rest = re.sub(r"[aeiouyhw]", "", w[1:])
    rest = re.sub(r"(.)\1+", r"\1", rest)
    return first + rest


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def best_match(word, vocab, table):
    low = word.lower()
    if low in vocab:
        return None
    if low in table and table[low] in vocab | set(table.values()):
        return table[low], 1.0
    if len(low) < 3:
        return None
    scored = []
    code = phonetic(low)
    for v in vocab:
        if abs(len(v) - len(low)) > 2 or len(v) < 3:
            continue
        d = levenshtein(low, v)
        if d <= 1 or (code and code == phonetic(v) and d <= 2):
            scored.append((d, v))
    if not scored:
        return None
    scored.sort()
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1], 0.8 if scored[0][0] <= 1 else 0.6


def correction_candidates(text):
    words = text.split()
    lows = [w.lower().strip(",.") for w in words]
    options = []
    if QUESTION_START.match(text.strip()):
        return options
    verbs = set(VERB_SYNONYMS) - EXPLICIT_ONLY_VERBS
    for i, low in enumerate(lows):
        clause_start = i == 0 or lows[i - 1] in CONNECTOR_WORDS or words[i - 1].endswith((",", "."))
        prev = lows[i - 1] if i else None
        if low in NEVER_CORRECT:
            hit = None
        elif clause_start:
            hit = best_match(low, verbs, CONFUSIONS["verb"])
        elif prev in ("press", "hit"):
            hit = best_match(low, KEY_VOCAB, CONFUSIONS["key"])
        elif prev in DIRECTION_VERBS:
            hit = best_match(low, {"up", "down", "mute"}, CONFUSIONS["direction"])
        elif prev == "search":
            hit = (CONFUSIONS["for"][low], 1.0) if low in CONFUSIONS["for"] else None
        else:
            hit = None
        if hit:
            options.append((i, words[i], hit[0], hit[1]))
    return options


def apply_corrections(text, options):
    words = text.split()
    for i, _, new, _ in options:
        words[i] = new
    return " ".join(words)


KNOWN_NAMES = {k.replace(" ", "") for k in list(APP_INDEX) + list(WEBSITES)}


def join_split_names(text, steps):
    spans = protected_spans(text)
    words = text.split(" ")
    offsets, pos = [], 0
    for w in words:
        offsets.append(pos)
        pos += len(w) + 1
    out, i, changed = [], 0, False
    while i < len(words):
        if i + 1 < len(words) and not _inside(offsets[i], spans):
            a, b = words[i], words[i + 1]
            head, dot, tail = b.partition(".")
            joined = (a + head).lower().replace("'", "")
            lone = {a.lower().replace("'", ""), head.lower().replace("'", "")}
            if joined in KNOWN_NAMES and not lone & KNOWN_NAMES:
                out.append(a.replace("'", "") + head + (dot + tail if dot else ""))
                i += 2
                changed = True
                continue
        out.append(words[i])
        i += 1
    new = " ".join(out)
    if changed:
        steps.append(Step("rewrite", "join split name", text, new))
    return new


def understand(transcript):
    steps = []
    text = normalize_transcript(transcript or "")
    if text != (transcript or "").strip():
        steps.append(Step("normalize", "transcript cleanup", (transcript or "").strip(), text))
    spelled = SPELLED.sub(lambda m: m.group(1).replace(".", "").replace(" ", "") + " ", text).strip()
    if spelled != text:
        steps.append(Step("normalize", "spelled letters", text, spelled))
        text = spelled
    stripped = FILLERS.sub("", text).strip()
    if stripped != text:
        steps.append(Step("disfluency", "filler sounds", text, stripped))
        text = stripped
    text = apply_rules(text, POLITE_RULES, "disfluency", steps)
    text = resolve_self_corrections(text, steps)
    text = apply_rules(text, POLITE_RULES, "disfluency", steps)
    text = join_split_names(text, steps)
    text = apply_rules(text, REWRITE_RULES, "rewrite", steps)
    return Understanding(original=transcript, text=text, steps=steps)


def corrected_variants(u: Understanding, limit=8):
    options = correction_candidates(u.text)
    variants = []
    if not options:
        return variants
    seen = set()
    full = apply_corrections(u.text, options)
    candidates = [options] + [[o] for o in options]
    for combo in candidates:
        new_text = apply_corrections(u.text, combo)
        if new_text in seen or new_text == u.text:
            continue
        seen.add(new_text)
        redone = understand(new_text)
        confident = all(score >= 0.8 for *_, score in combo)
        variants.append(Understanding(
            original=u.original, text=redone.text,
            steps=u.steps + [Step("correction", f"{old} -> {new}", u.text, new_text) for _, old, new, _ in combo] + redone.steps[1:],
            corrections=[(old, new) for _, old, new, _ in combo], confident=confident,
        ))
        if len(variants) >= limit:
            break
    if full not in seen:
        pass
    return variants


def explain(u: Optional[Understanding]):
    if u is None:
        return ""
    return "\n".join(f"  [{s.stage}] {s.rule}: {s.before!r} -> {s.after!r}" for s in u.steps)
