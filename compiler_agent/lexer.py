import re
from dataclasses import dataclass, field
from enum import Enum, auto

from .registry import KEY_ALIASES, resolve_app


class TokenType(Enum):
    VERB = auto()
    STRING = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    PREP = auto()
    CONNECTOR = auto()
    KEYWORD = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: object
    pos: int
    text: str = field(default="", compare=False)

    def __repr__(self):
        return f"<{self.type.name}:{self.value!r}>"


VERB_SYNONYMS = {
    "take": "SCREENSHOT", "capture": "SCREENSHOT", "screenshot": "SCREENSHOT", "snap": "SCREENSHOT",
    "open": "OPEN_APP", "launch": "OPEN_APP", "start": "OPEN_APP", "run": "OPEN_APP", "execute": "OPEN_APP",
    "type": "TYPE_TEXT", "write": "TYPE_TEXT", "dictate": "TYPE_TEXT",
    "add": "TYPE_TEXT", "insert": "TYPE_TEXT", "put": "TYPE_TEXT",
    "copy": "COPY",
    "paste": "PASTE",
    "save": "SAVE_FILE",
    "create": "CREATE_FILE", "make": "CREATE_FILE",
    "delete": "DELETE_FILE", "remove": "DELETE_FILE",
    "close": "CLOSE_APP", "quit": "CLOSE_APP", "exit": "CLOSE_APP",
    "click": "CLICK",
    "switch": "SWITCH_APP", "focus": "SWITCH_APP",
    "search": "SEARCH",
    "go": "OPEN_URL", "visit": "OPEN_URL", "browse": "OPEN_URL",
    "press": "PRESS", "hit": "PRESS",
    "wait": "WAIT", "pause": "WAIT", "sleep": "WAIT",
    "scroll": "SCROLL",
    "select": "SELECT",
    "volume": "VOLUME", "mute": "VOLUME", "unmute": "VOLUME",
    "increase": "VOLUME", "decrease": "VOLUME", "raise": "VOLUME", "lower": "VOLUME",
    "minimize": "MINIMIZE", "minimise": "MINIMIZE", "maximize": "MAXIMIZE", "maximise": "MAXIMIZE",
    "lock": "LOCK", "tell": "TELL", "chat": "CHAT", "play": "PLAY",
    "calculate": "CALCULATE", "compute": "CALCULATE", "evaluate": "CALCULATE",
}

DICTATION_VERBS = {"TYPE_TEXT", "SEARCH", "CLICK", "CALCULATE", "CHAT", "PLAY"}
KEY_VERBS = {"PRESS"}
DICTATION_LEADING = {
    "TYPE_TEXT": {"out"},
    "SEARCH": {"for", "about", "google", "on", "up", "the", "web"},
    "CLICK": {"on", "the", "at"},
}

PRESS_KEYS = set(KEY_ALIASES) | {"control", "page", "f5", "f2", "f11"}
TITLE_WORDS = {"title", "heading"}
TITLE_LINKS = {"as", "called", "named", "of", "to"}
APP_PREPOSITIONS = {"in", "into", "inside", "on"}

CONNECTOR_WORDS = {"and", "then"}
PUNCT_CONNECTORS = {",", ";", ".", "!", "?"}
SEQUENCE_FILLER = {"after", "that", "next", "finally", "also", "now"}

KEYWORDS = {
    "if": "IF", "otherwise": "ELSE", "else": "ELSE",
    "repeat": "REPEAT", "times": "TIMES", "time": "TIMES",
    "exists": "EXISTS", "exist": "EXISTS", "missing": "MISSING",
    "is": "IS", "are": "IS", "not": "NOT", "running": "RUNNING",
    "end": "END", "endif": "END",
}
NEGATIONS = {"doesn't": ["NOT"], "don't": ["NOT"], "isn't": ["IS", "NOT"], "aren't": ["IS", "NOT"]}

DETERMINERS = {"the", "a", "an", "this", "that", "my"}
FILLER = DETERMINERS | {
    "into", "in", "to", "from", "on", "onto", "of", "for", "with", "at", "it",
    "please", "can", "you", "could", "would", "will", "now", "just", "me",
    "called", "named", "does", "do", "after", "next", "finally", "also", "as",
}

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
ADVERB_COUNTS = {"once": 1, "twice": 2, "thrice": 3}

_SPOKEN_QUOTE = re.compile(
    r"\b(?:open\s+|begin\s+|start\s+)?quote\b\s*(.*?)\s*\b(?:close\s+quote|end\s+quote|unquote)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(
    r"\"([^\"]*)\""
    r"|(?<!\w)'([^']*)'(?!\w)"
    r"|(https?://\S+|[A-Za-z]:[\\/][^\s\"]*)"
    r"|([A-Za-z0-9_~+*\-\\/]+(?:[.'][A-Za-z0-9_~+*\-\\/]+)*)"
    r"|([,;.!?])"
)


class LexerError(Exception):
    pass


def number_value(word):
    if word is None:
        return None
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def preprocess(text):
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return _SPOKEN_QUOTE.sub(lambda m: '"' + m.group(1) + '"', text)


class Lexer:
    def __init__(self, text: str):
        if not isinstance(text, str):
            raise LexerError("Command must be a string")
        self.source = text
        self.text = preprocess(text)
        if self.text.count('"') % 2:
            raise LexerError("Unclosed quotation mark in command")

    def tokenize(self):
        matches = list(_TOKEN_RE.finditer(self.text))
        tokens = []
        i = 0
        while i < len(matches):
            produced = self._classify(matches[i], tokens[-1] if tokens else None)
            tokens.extend(produced)
            i += 1
            last = produced[-1] if produced else None
            if last is not None and last.type == TokenType.VERB:
                if last.value in DICTATION_VERBS and i < len(matches) and not self._is_string(matches[i]):
                    i = self._dictation(matches, i, last.value, tokens)
                elif last.value in KEY_VERBS:
                    i = self._keys(matches, i, tokens)
        tokens = self._cleanup(tokens)
        tokens.append(Token(TokenType.EOF, "", len(self.text)))
        return tokens

    @staticmethod
    def _is_string(m):
        return m.group(1) is not None or m.group(2) is not None

    @staticmethod
    def _word(m):
        if m.group(4) is not None:
            return m.group(4).lower()
        if m.group(5) is not None:
            return m.group(5)
        return None

    def _classify(self, m, prev):
        pos = m.start()
        if self._is_string(m):
            value = m.group(1) if m.group(1) is not None else m.group(2)
            return [Token(TokenType.STRING, value, pos, value)]
        if m.group(3) is not None:
            return [Token(TokenType.IDENTIFIER, m.group(3), pos, m.group(3))]
        if m.group(5) is not None:
            return [Token(TokenType.CONNECTOR, "and", pos, m.group(5))]
        word = m.group(4)
        lw = word.lower()
        if lw in CONNECTOR_WORDS:
            return [Token(TokenType.CONNECTOR, lw, pos, word)]
        if lw in ADVERB_COUNTS:
            return [Token(TokenType.NUMBER, ADVERB_COUNTS[lw], pos, word), Token(TokenType.KEYWORD, "TIMES", pos, word)]
        n = number_value(lw)
        if n is not None:
            return [Token(TokenType.NUMBER, n, pos, word)]
        if lw in NEGATIONS:
            return [Token(TokenType.KEYWORD, k, pos, word) for k in NEGATIONS[lw]]
        if lw in ("time", "times") and prev is not None and prev.type == TokenType.VERB and prev.value == "TELL":
            return [Token(TokenType.IDENTIFIER, word, pos, word)]
        if lw in KEYWORDS:
            return [Token(TokenType.KEYWORD, KEYWORDS[lw], pos, word)]
        if lw in VERB_SYNONYMS:
            if prev is not None and prev.type == TokenType.PREP and prev.value in DETERMINERS:
                return [Token(TokenType.IDENTIFIER, word, pos, word)]
            return [Token(TokenType.VERB, VERB_SYNONYMS[lw], pos, word)]
        if lw in FILLER:
            return [Token(TokenType.PREP, lw, pos, word)]
        return [Token(TokenType.IDENTIFIER, word, pos, word)]

    def _starts_new_statement(self, matches, k):
        n = len(matches)
        j = k + 1
        while j < n and (self._word(matches[j]) in CONNECTOR_WORDS
                         or self._word(matches[j]) in PUNCT_CONNECTORS
                         or self._word(matches[j]) in SEQUENCE_FILLER):
            j += 1
        if j >= n:
            return False
        w = self._word(matches[j])
        return w in VERB_SYNONYMS or w in ("if", "repeat")

    def _is_boundary(self, matches, k):
        w = self._word(matches[k])
        if w in ("press", "hit") and k + 1 < len(matches) and self._word(matches[k + 1]) in PRESS_KEYS:
            return True
        if w in ("otherwise", "else"):
            return True
        if w == "end" and k + 1 < len(matches) and self._word(matches[k + 1]) in ("if", "repeat"):
            return True
        if w in CONNECTOR_WORDS or w in PUNCT_CONNECTORS:
            return self._starts_new_statement(matches, k)
        return False

    def _dictation(self, matches, i, verb, tokens):
        n = len(matches)
        start = i
        skip = DICTATION_LEADING.get(verb, set())
        while start < n and self._word(matches[start]) in skip:
            start += 1
        if verb == "TYPE_TEXT" and start < n and self._word(matches[start]) in TITLE_WORDS:
            start += 1
            while start < n and self._word(matches[start]) in TITLE_LINKS:
                start += 1
        end = start
        while end < n and not self._is_boundary(matches, end):
            end += 1
        stop = end
        words = [self._word(matches[k]) for k in range(start, stop)]
        if len(words) >= 2 and words[-1] in ("times", "time") and number_value(words[-2]) is not None:
            stop -= 2
        elif words and words[-1] in ADVERB_COUNTS:
            stop -= 1
        if verb == "TYPE_TEXT":
            stop = self._split_trailing_app(matches, start, stop)
        if stop > start:
            s = matches[start].start()
            while s > 0 and self.text[s - 1] in "([":
                s -= 1
            end_at = len(self.text) if stop == n and verb != "CLICK" else matches[stop - 1].end()
            raw = self.text[s:end_at].strip(" ,;")
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                raw = raw[1:-1]
            if raw:
                tokens.append(Token(TokenType.STRING, raw, s, raw))
        return stop

    def _split_trailing_app(self, matches, start, stop):
        if stop - 2 >= start and self._word(matches[stop - 2]) in APP_PREPOSITIONS | {"to"}:
            last = self._word(matches[stop - 1])
            if last and re.search(r"\.[a-z0-9]{1,6}$", last) and not last.startswith("www."):
                return stop - 2
        for size in (3, 2, 1):
            prep = stop - size - 1
            if prep < start:
                continue
            if self._word(matches[prep]) not in APP_PREPOSITIONS:
                continue
            words = [self._word(matches[k]) for k in range(prep + 1, stop)]
            if any(w is None for w in words):
                continue
            if resolve_app(" ".join(words)):
                return prep
        return stop

    def _keys(self, matches, i, tokens):
        n = len(matches)
        while i < n:
            m = matches[i]
            w = self._word(m)
            if w is None or w in CONNECTOR_WORDS or w in PUNCT_CONNECTORS:
                break
            if number_value(w) is not None or w in ADVERB_COUNTS or w in ("times", "time", "otherwise", "else", "if"):
                break
            if w == "end" and i + 1 < n and self._word(matches[i + 1]) in ("if", "repeat"):
                break
            tokens.append(Token(TokenType.IDENTIFIER, w, m.start(), m.group(4)))
            i += 1
        return i

    @staticmethod
    def _cleanup(tokens):
        merged = []
        for tok in tokens:
            prev = merged[-1] if merged else None
            if (tok.type == TokenType.NUMBER and prev is not None and prev.type == TokenType.NUMBER
                    and prev.value >= 20 and prev.value % 10 == 0 and 0 < tok.value < 10):
                merged[-1] = Token(TokenType.NUMBER, prev.value + tok.value, prev.pos, f"{prev.text} {tok.text}")
                continue
            if tok.type == TokenType.CONNECTOR and (prev is None or prev.type == TokenType.CONNECTOR):
                continue
            merged.append(tok)
        while merged and merged[-1].type == TokenType.CONNECTOR:
            merged.pop()
        return merged
