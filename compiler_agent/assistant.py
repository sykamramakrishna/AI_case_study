import re
from dataclasses import dataclass, field
from typing import List, Optional

from .agent import Agent, CompilationError
from .executor import ExecutionError
from .lexer import VERB_SYNONYMS, LexerError
from .memory_store import is_sensitive
from .nlu import Step, Understanding, _inside, corrected_variants, protected_spans, understand
from .parser import ParserError
from .registry import suggest_name
from .semantic_analyzer import SemanticError

QUESTIONS = {
    ("DELETE_FILE", "target"): "Which file should I delete?",
    ("OPEN_APP", "target"): "What should I open?",
    ("OPEN_URL", "target"): "Which website?",
    ("TYPE_TEXT", "text"): "What should I type?",
    ("CLOSE_APP", "target"): "Which app should I close?",
    ("SWITCH_APP", "target"): "Which app should I switch to?",
    ("SEARCH", "text"): "What should I search for?",
    ("CREATE_FILE", "target"): "What should the file be called?",
    ("CREATE_FILE", "filename"): "What should the file be called? Include the extension, like notes.txt.",
    ("CREATE_FOLDER", "target"): "What should the folder be called?",
    ("PRESS", "target"): "Which key should I press?",
    ("WAIT", "number"): "How many seconds should I wait?",
    ("CLICK", "text"): "What should I click on?",
    ("SCROLL", "target"): "Scroll up or down?",
    ("CALCULATE", "text"): "What should I calculate?",
    ("CHAT", "text"): "Who should I open the WhatsApp chat with?",
    ("PLAY", "text"): "What should I play?",
}
CANCEL = re.compile(r"^(?:cancel|never ?mind|forget it|stop|leave it|no thanks|nothing)\b", re.I)
YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok(?:ay)?|correct|right|do it|go ahead|confirm)\b", re.I)
NO = re.compile(r"^(?:no|nope|nah|wrong|not that)\b", re.I)
AGAIN = re.compile(r"^(?:(?:do|run|try)\s+(?:it|that|this)\s+again|again|repeat(?:\s+(?:it|that|the last (?:command|one)))?|one more time|same again)$", re.I)
CROSS_TURN_FIX = re.compile(r"^(?:no|nope|wrong|not that)[,\s]+(?:i\s+(?:said|meant|mean)\s+|it'?s\s+|use\s+)?(.+)$", re.I)
POWER = re.compile(r"\b(?:shut\s*down|power\s*off|turn\s*off|restart|reboot|log\s*(?:off|out)|sign\s*out|hibernate)\b(?:\s+(?:the|my|this))?\s*(?:computer|pc|laptop|system|machine|windows|device)?\s*$", re.I)
PRONOUN = re.compile(r"\b(it|that|this|them)\b", re.I)
APP_PRONOUN_VERBS = {"close", "quit", "exit", "switch", "focus", "minimize", "maximize", "kill"}
FILE_PRONOUN_VERBS = {"delete", "remove", "run", "execute"}
FIX_REQUEST = re.compile(r"^(?:please\s+)?(?:fix|correct|repair|debug)\s+(?:it|that|the (?:errors?|bugs?|script|code|problem)|this|the issue)", re.I)
QUESTION = re.compile(r"^(?:what|why|how|who|when|where|which|explain|define|tell me about|describe|is|are|can|does|do)\b", re.I)
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_\- ]{1,60}\.py$")
MAX_FIX_ATTEMPTS = 3
REMEMBER_ALIAS = re.compile(r"^(?:please\s+)?(?:remember|note|save)\s+(?:that\s+)?(?:my\s+)?(.+?)\s+(?:is|means|=|refers to)\s+(.+)$", re.I)
REMEMBER_NOTE = re.compile(r"^(?:please\s+)?(?:remember|note down|make a note)\s+(?:that\s+)?(.+)$", re.I)
RECALL = re.compile(r"^(?:what do you (?:remember|know)(?: about me)?|show (?:me )?(?:my |your )?memory|list (?:my )?(?:memory|aliases|shortcuts)|what have you saved)$", re.I)
FORGET_ALL = re.compile(r"^forget (?:everything|all)(?: (?:you (?:know|remember)|about me))?$|^(?:forget|erase|clear|wipe|delete) (?:all )?(?:of )?(?:my |your )?(?:memory|memories|saved data|everything you (?:know|remember))$", re.I)
FORGET = re.compile(r"^forget (?:about )?(?:that )?(?:my )?(.+)$", re.I)
HISTORY_OFF = re.compile(r"^(?:stop|don't|do not) (?:saving|keeping|recording|remembering) (?:my )?(?:history|commands)$", re.I)
HISTORY_ON = re.compile(r"^(?:start|resume) (?:saving|keeping) (?:my )?(?:history|commands)$", re.I)
SAVE_CONTACT = re.compile(r"^(?:save|add|store|remember)\s+(?:contact\s+)?(?:that\s+)?(?:the\s+)?([a-z][a-z .'-]{0,40}?)(?:'s|s)?\s+(?:number|phone|phone number|whatsapp number|mobile|mobile number)?\s*(?:as|is|=|:)?\s*(\+?[\d][\d\s-]{8,18}\d)$", re.I)
CONTACT_IS = re.compile(r"^([a-z][a-z .'-]{0,40}?)(?:'s|s)\s+(?:number|phone number|whatsapp number|mobile number|mobile)\s+is\s+(\+?[\d][\d\s-]{8,18}\d)$", re.I)
FORGET_CONTACT = re.compile(r"^(?:forget|delete|remove)\s+([a-z][a-z .'-]{0,40}?)(?:'s|s)\s+(?:number|contact|phone number)$", re.I)
START_DICTATION = re.compile(r"^(?:start|begin|turn on|enable)\s+(?:dictation|dictating|dictation mode|writing mode|typing mode|continuous typing)(?:\s+(?:in|into|on)\s+(.+))?$|^(?:take notes|let me dictate|i will dictate|start writing(?:\s+(?:in|into)\s+(.+))?)$", re.I)
STOP_DICTATION = re.compile(r"^(?:stop|end|finish|exit|done|turn off|disable|close)(?:\s+(?:the\s+)?(?:dictation|dictating|writing|typing|dictation mode))?$|^(?:that's all|thats all|i'm done|im done)$", re.I)
COMPOSE = re.compile(r"^(?:please\s+)?(?:write|compose|draft|generate|type out|create)\s+(?:me\s+)?(?:a|an|some|the|one|two|three|\d+)?\s*(?:short\s+|long\s+|small\s+|detailed\s+|formal\s+|simple\s+)?(paragraphs?|essay|letter|poem|story|email|mail|notes?|summary|article|report|speech|introduction|description|message|application|leave letter|lines?|points?|sentences?|code|program|answer|explanation|definition)\s+(about|on|for|to|regarding|explaining|describing|of)\s+(.+)$", re.I)
SPOKEN_PUNCT = [
    (r"\s*\b(?:new paragraph)\b\s*", "\n\n"), (r"\s*\b(?:new line|next line|line break)\b\s*", "\n"),
    (r"\s*\b(?:full stop|period)\b", "."), (r"\s*\bcomma\b", ","), (r"\s*\bquestion mark\b", "?"),
    (r"\s*\b(?:exclamation mark|exclamation point)\b", "!"), (r"\s*\bsemicolon\b", ";"), (r"\s*\bcolon\b", ":"),
    (r"\s*\b(?:open bracket)\b\s*", " ("), (r"\s*\b(?:close bracket)\b", ")"), (r"\s*\bhyphen\b\s*", "-"),
]


def dictation_text(spoken, first):
    text = spoken.strip()
    for pattern, repl in SPOKEN_PUNCT:
        text = re.sub(pattern, repl, text, flags=re.I)
    text = re.sub(r"([.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    if text and (first or text[0].isalpha()):
        text = text[0].upper() + text[1:] if first else text
    return ("" if first or text.startswith(("\n", ".", ",", "?", "!")) else " ") + text


CLEAR_HISTORY = re.compile(r"^(?:clear|delete|erase) (?:my |the )?(?:command )?history$", re.I)


@dataclass
class Pending:
    kind: str
    base: str = ""
    question: str = ""
    suggestion: Optional[str] = None


@dataclass
class Outcome:
    kind: str
    message: str = ""
    ir: Optional[list] = None
    text: str = ""
    understanding: Optional[Understanding] = None
    results: List[str] = field(default_factory=list)
    source: str = "grammar"
    error: Optional[str] = None
    timings: dict = field(default_factory=dict)


class Assistant:
    def __init__(self, dry_run=True, speak=None, llm=None, confirm=None, echo=False, optimize=True, memory=None,
                 policy=None, on_progress=None, llm_autorun=True):
        self.on_progress = on_progress
        self.on_thinking = None
        self.llm_autorun = llm_autorun
        self.agent = Agent(dry_run=dry_run, confirm=confirm, echo=echo, optimize=optimize, policy=policy)
        self.speak = speak
        self.llm = llm
        self.memory = memory
        self.pending: Optional[Pending] = None
        self.last_text: Optional[str] = None
        self.last_app: Optional[str] = None
        self.last_file: Optional[str] = None
        self.history: List[Outcome] = []
        self.last_failure = None
        self.fix_attempts = {}
        self.dictating = None

    def _try_compile(self, text):
        try:
            ir = self.agent.compile(text)
            warnings = self.agent.last.warnings if self.agent.last else []
            return ir, None, warnings
        except CompilationError as e:
            return None, e.__cause__ or e, []

    def _resolve_references(self, text):
        words = text.split()
        out = []
        for i, w in enumerate(words):
            low = w.lower().strip(",.")
            prev = words[i - 1].lower() if i else ""
            prev2 = words[i - 2].lower() if i > 1 else ""
            if low in ("it", "that", "this", "them"):
                verb = prev if prev in APP_PRONOUN_VERBS | FILE_PRONOUN_VERBS else (prev2 if prev == "to" else "")
                if verb in APP_PRONOUN_VERBS and self.last_app:
                    out.append(self.last_app)
                    continue
                if verb in FILE_PRONOUN_VERBS and self.last_file:
                    out.append(self.last_file)
                    continue
            out.append(w)
        return " ".join(out)

    def _clarify_for(self, error, text):
        if isinstance(error, SemanticError) and error.missing:
            question = QUESTIONS.get((error.verb, error.missing))
            if question:
                return question
        return None

    def _apply_aliases(self, u):
        if self.memory is None:
            return u
        aliases = self.memory.aliases()
        if not aliases:
            return u
        text = u.text
        for name, target in aliases.items():
            spans = protected_spans(text)
            pattern = re.compile(r"(?<![\w])(?:my\s+|the\s+)?" + re.escape(name) + r"(?![\w])", re.I)
            new = pattern.sub(lambda m: m.group(0) if _inside(m.start(), spans) else target, text)
            if new != text:
                u.steps.append(Step("memory", f"alias '{name}'", text, new))
                text = new
        u.text = text
        return u

    def _contact_command(self, clean):
        m = SAVE_CONTACT.match(clean) or CONTACT_IS.match(clean)
        f = FORGET_CONTACT.match(clean)
        if not m and not f:
            return None
        if self.memory is None:
            return Outcome("reject", "Memory is turned off, so I can't save contacts in this session.")
        if f:
            n = self.memory.forget_contact(f.group(1))
            return Outcome("memory", f"Removed {f.group(1)}'s number." if n else f"I didn't have a number for {f.group(1)}.")
        name, phone = m.group(1).strip(), m.group(2)
        try:
            digits = self.memory.set_contact(name, phone)
        except ValueError as e:
            return Outcome("reject", str(e).capitalize() + ".")
        return Outcome("memory", f"Saved {name}'s WhatsApp number ending {digits[-4:]}. Now say: open WhatsApp chat with {name}.")

    def _start_dictation(self, where):
        ir = []
        app = None
        if where:
            u = understand(f"open {where}")
            compiled, err, _ = self._try_compile(u.text)
            if compiled is None:
                return Outcome("reject", f"I couldn't find '{where}' to dictate into.", error=str(err))
            ir = compiled
            app = next((op["args"].get("app") for op in compiled if op["args"].get("app")), None)
        self.dictating = {"app": app, "first": True}
        message = ("Dictation is on. Everything you say will be typed" + (f" into {app}" if app else " where your cursor is")
                   + ". Say 'new line' or 'full stop' for punctuation, and 'stop dictation' when you're done.")
        if ir:
            return Outcome("ir", message, ir=ir, text=f"open {where}", source="dictation")
        return Outcome("dictation", message, text="start dictation", source="dictation")

    def _dictation_turn(self, text):
        clean = text.strip(" .!?")
        if STOP_DICTATION.match(clean):
            self.dictating = None
            return Outcome("dictation", "Dictation stopped.", text="stop dictation", source="dictation")
        typed = dictation_text(text, self.dictating["first"])
        self.dictating["first"] = False
        ir = []
        if self.dictating.get("app"):
            ir.append({"op": "SWITCH_APP", "target": self.dictating["app"], "args": {"app": self.dictating["app"]}})
        ir.append({"op": "TYPE_TEXT", "target": None, "args": {"text": typed}})
        return Outcome("ir", text=f"type {typed.strip()}", ir=ir, source="dictation")

    def _compose(self, m):
        kind, prep, rest = m.group(1), m.group(2), m.group(3).strip()
        target = None
        where = re.search(r"\s+(?:in|into|on)\s+([\w .]+?)$", rest, re.I)
        if where:
            from .registry import resolve_app
            app = resolve_app(where.group(1))
            if app:
                target, rest = app, rest[:where.start()].strip()
        if self.llm is None or not hasattr(self.llm, "compose"):
            return Outcome("reject", "Writing a whole " + kind + " needs the local AI model. Start the app with --llm.",
                           text=m.group(0))
        import time
        started = time.perf_counter()
        self._thinking(f"Writing the {kind}.")
        try:
            content = self.llm.compose(f"Write a {kind} {prep} {rest}.")
        except Exception as e:
            return Outcome("reject", f"The local AI model is not available: {e}", text=m.group(0))
        content = (content or "").strip()
        if not content:
            return Outcome("reject", "The AI returned nothing to write.", text=m.group(0))
        ir = []
        if target:
            ir.append({"op": "OPEN_APP", "target": target, "args": {"app": target}})
            ir.append({"op": "WAIT", "target": None, "args": {"seconds": 1}})
        ir.append({"op": "TYPE_TEXT", "target": None, "args": {"text": content}})
        out = Outcome("ir", text=f"write a {kind} {prep} {rest}" + (f" in {target}" if target else ""), ir=ir,
                      source="ai-writing", results=[])
        out.timings["ai_ms"] = round((time.perf_counter() - started) * 1000)
        return out

    def _memory_command(self, clean):
        if not any(r.match(clean) for r in (REMEMBER_ALIAS, REMEMBER_NOTE, RECALL, FORGET_ALL, FORGET,
                                            HISTORY_OFF, HISTORY_ON, CLEAR_HISTORY)):
            return None
        if self.memory is None:
            return Outcome("reject", "Memory is turned off in this session.")
        if RECALL.match(clean):
            lines = self.memory.summary()
            return Outcome("memory", "Here's what I have saved: " + "; ".join(lines) + ".")
        if FORGET_ALL.match(clean):
            self.pending = Pending("confirm_forget_all", question="Delete everything I've saved about you?")
            return Outcome("clarify", self.pending.question)
        if CLEAR_HISTORY.match(clean):
            self.memory.clear_history()
            return Outcome("memory", "Command history cleared.")
        if HISTORY_OFF.match(clean):
            self.memory.set_pref("history", "off")
            return Outcome("memory", "Okay, I won't save your commands any more.")
        if HISTORY_ON.match(clean):
            self.memory.set_pref("history", "on")
            return Outcome("memory", "Okay, I'll keep a history of commands again.")
        m = FORGET.match(clean)
        if m:
            removed = self.memory.forget(m.group(1))
            return Outcome("memory", f"Forgot '{m.group(1)}'." if removed else f"I had nothing saved about '{m.group(1)}'.")
        m = REMEMBER_ALIAS.match(clean)
        try:
            if m:
                name, target = m.group(1).strip(), m.group(2).strip()
                self.memory.set_alias(name, target)
                return Outcome("memory", f"Got it: '{name}' means {target}.")
            m = REMEMBER_NOTE.match(clean)
            self.memory.add_note(m.group(1))
            return Outcome("memory", f"Noted: {m.group(1)}")
        except ValueError as e:
            return Outcome("reject", f"I won't save that: {e}.")

    def _candidates(self, transcripts):
        primary, corrected = [], []
        for t in transcripts:
            u = self._apply_aliases(understand(t))
            u.text = self._resolve_references(u.text)
            primary.append(u)
        for u in primary:
            for v in corrected_variants(u):
                v.text = self._resolve_references(v.text)
                corrected.append(v)
        return primary, corrected

    def interpret(self, text, alternatives=None) -> Outcome:
        text = (text or "").strip()
        if not text:
            return Outcome("reject", "I didn't hear anything.")
        if self.pending is not None:
            handled = self._answer_pending(text, alternatives)
            if handled is not None:
                return handled
        if self.dictating is not None:
            return self._dictation_turn(text)
        start = START_DICTATION.match(text.strip(" .!?"))
        if start:
            return self._start_dictation(start.group(1) or start.group(2))
        if FIX_REQUEST.match(text.strip()):
            return self._fix_last_failure()
        contact_reply = self._contact_command(text.strip(" .!?"))
        if contact_reply is not None:
            return contact_reply
        compose = COMPOSE.match(text.strip(" .!?"))
        if compose:
            return self._compose(compose)
        memory_reply = self._memory_command(text.strip(" .!?"))
        if memory_reply is not None:
            return memory_reply
        if AGAIN.match(text.strip(" .!?")):
            if not self.last_text:
                return Outcome("reject", "There is no previous command to repeat yet.")
            return self._compile_outcome(understand(self.last_text), "repeat")
        fix = CROSS_TURN_FIX.match(text.strip(" .!?"))
        if fix and self.last_text:
            return self._cross_turn_fix(fix.group(1))
        if POWER.search(understand(text).text) or POWER.search(text):
            return Outcome("reject", "For safety I don't shut down, restart or log off the computer.", text=text)
        transcripts = [text] + [a for a in (alternatives or []) if a and a != text]
        primary, corrected = self._candidates(transcripts)
        first_error = None
        unregistered = None
        for u in primary:
            ir, err, warnings = self._try_compile(u.text)
            if ir is not None and not any("not a registered app" in w for w in warnings):
                return self._ok(u, ir, "grammar" if u is primary[0] else "alternative")
            if ir is not None and unregistered is None:
                unregistered = (u, ir)
            if err is not None and first_error is None:
                first_error = (u, err)
        for v in corrected:
            ir, err, warnings = self._try_compile(v.text)
            if ir is not None and not any("not a registered app" in w for w in warnings):
                if v.confident:
                    return self._ok(v, ir, "corrected")
                self.pending = Pending("confirm_fix", suggestion=v.text, question=f"Did you mean: “{v.text}”?")
                return Outcome("clarify", self.pending.question, text=v.text, understanding=v)
        if unregistered is not None:
            u, ir = unregistered
            name = next((op["args"].get("app") for op in ir if op["args"].get("unregistered_app")), None)
            hint = suggest_name(name)
            if hint and hint != name:
                fixed = re.sub(re.escape(name), hint, u.text, count=1, flags=re.I)
                self.pending = Pending("confirm_fix", suggestion=fixed,
                                       question=f"I don't know an app called '{name}'. Did you mean {hint}?")
                return Outcome("clarify", self.pending.question, text=fixed, understanding=u)
            return self._ok(u, ir, "grammar")
        if first_error is not None:
            u, err = first_error
            if isinstance(err, SemanticError) and err.missing == "unknown_app":
                name = re.search(r"called '([^']+)'", str(err))
                hint = suggest_name(name.group(1)) if name else None
                if hint:
                    fixed = re.sub(re.escape(name.group(1)), hint, u.text, count=1, flags=re.I)
                    self.pending = Pending("confirm_fix", suggestion=fixed,
                                           question=f"I don't know an app called '{name.group(1)}'. Did you mean {hint}?")
                    return Outcome("clarify", self.pending.question, text=fixed, understanding=u)
            question = self._clarify_for(err, u.text)
            prefer_llm = self.llm is not None and isinstance(err, SemanticError) and err.missing == "filename"
            if question and not prefer_llm:
                base = (err.word or "create") if err.missing == "filename" else u.text
                self.pending = Pending("slot", base=base, question=question)
                return Outcome("clarify", question, text=u.text, understanding=u)
        understood_but_invalid = (first_error is not None and isinstance(first_error[1], SemanticError)
                                  and first_error[1].missing not in ("filename", "unknown_app"))
        if self.llm is not None and not understood_but_invalid:
            llm_out = self._ask_llm(text, primary[0])
            if llm_out is not None:
                return llm_out
        u, err = first_error if first_error else (primary[0], None)
        reason = str(err) if err else "I couldn't understand that."
        if QUESTION.match(text) and self.llm is None:
            return Outcome("reject", "I can answer general questions once the free local AI model (Ollama) is set up. "
                           "For now I handle computer commands, the time, the date and calculations.",
                           text=u.text, understanding=u, error=reason)
        return Outcome("reject", self._friendly(err), text=u.text, understanding=u, error=reason)

    def _friendly(self, err):
        if err is None:
            return "Sorry, I didn't understand that."
        msg = str(err)
        msg = re.sub(r"^Step \d+ \('[^']*'\): ", "", msg)
        if isinstance(err, (ParserError, LexerError)):
            return "Sorry, I didn't understand that command. Try something like 'open notepad' or 'search for …'."
        return msg[0].upper() + msg[1:] if msg else "Sorry, I didn't understand that."

    def _ok(self, u, ir, source):
        return Outcome("ir", text=u.text, ir=ir, understanding=u, source=source)

    def _compile_outcome(self, u, source):
        ir, err, _ = self._try_compile(u.text)
        if ir is None:
            return Outcome("reject", self._friendly(err), text=u.text, understanding=u, error=str(err))
        return self._ok(u, ir, source)

    def _answer_pending(self, text, alternatives):
        pending = self.pending
        clean = text.strip(" .!?")
        if CANCEL.match(clean):
            self.pending = None
            return Outcome("cancelled", "Okay, cancelled.")
        if pending.kind == "confirm_forget_all":
            self.pending = None
            if YES.match(clean):
                self.memory.forget_all()
                return Outcome("memory", "Done. I've deleted everything I had saved.")
            return Outcome("cancelled", "Okay, I kept everything.")
        if pending.kind == "confirm_code":
            self.pending = None
            if YES.match(clean):
                ir = [{"op": "WRITE_FILE", "target": pending.base,
                       "args": {"text": pending.suggestion, "destructive": True}}]
                return Outcome("ir", text=f"write {pending.base}", ir=ir, source="llm-code")
            return Outcome("cancelled", "Okay, I won't write that file.")
        if pending.kind == "llm_task":
            if NO.match(clean) and len(clean.split()) <= 2:
                self.pending = None
                return Outcome("cancelled", "Okay, cancelled.")
            self.pending = None
            combined = f"Original request: {pending.base}\nMy answer to your question '{pending.question}': {clean}"
            return self._ask_llm(combined, understand(clean), original=pending.base) or Outcome(
                "reject", "Sorry, I couldn't work out what to do.", text=clean)
        if pending.kind == "confirm_fix":
            if YES.match(clean):
                self.pending = None
                return self._compile_outcome(understand(pending.suggestion), "confirmed")
            if NO.match(clean) and len(clean.split()) <= 2:
                self.pending = None
                return Outcome("cancelled", "Okay. Please say the command again.")
            self.pending = None
            return None
        if pending.kind == "slot":
            first = understand(clean).text.split()[0].lower() if clean else ""
            if first in VERB_SYNONYMS or first in ("if", "repeat"):
                self.pending = None
                return None
            self.pending = None
            combined = f"{pending.base} {clean}"
            u = understand(combined)
            ir, err, _ = self._try_compile(u.text)
            if ir is not None:
                return self._ok(u, ir, "clarified")
            question = self._clarify_for(err, u.text)
            if question:
                self.pending = Pending("slot", base=u.text, question=question)
                return Outcome("clarify", question, text=u.text, understanding=u)
            return Outcome("reject", self._friendly(err), text=u.text, understanding=u, error=str(err))
        self.pending = None
        return None

    def _cross_turn_fix(self, replacement):
        last = understand(self.last_text).text
        clauses = re.split(r"\s+(?:and|then)\s+|,\s*", last)
        final = clauses[-1].split()
        rep = understand(replacement).text
        if rep.split()[0].lower() in VERB_SYNONYMS:
            fixed = rep
        else:
            if rep.lower().startswith("not "):
                rep = " ".join(rep.split()[2:])
            fixed = f"{final[0]} {rep}" if final else rep
        u = understand(fixed)
        return self._compile_outcome(u, "corrected-by-user")

    def _thinking(self, message):
        if self.on_thinking is not None:
            try:
                self.on_thinking(message)
            except Exception:
                pass

    def _ask_llm(self, text, u, original=None):
        import time
        started = time.perf_counter()
        self._thinking("One moment.")
        try:
            proposal = self.llm.translate(text, context=self._context())
        except Exception as e:
            return Outcome("reject", f"The local AI model is not available: {e}", text=text, error=str(e))
        out = self._llm_outcome(proposal, text, u, original)
        if out is not None:
            out.timings["ai_ms"] = round((time.perf_counter() - started) * 1000)
        return out

    def _llm_outcome(self, proposal, text, u, original):
        if proposal is None:
            return Outcome("reject", "The AI model's reply could not be understood, so I did nothing.", text=text)
        if proposal.kind == "answer":
            return Outcome("answer", proposal.text, text=text, understanding=u, source="llm")
        if proposal.kind == "unsupported":
            return Outcome("reject", "I can't do that safely with the tools I have.", text=text, source="llm")
        if proposal.kind == "clarify":
            self.pending = Pending("llm_task", base=original or text, question=proposal.text)
            return Outcome("clarify", proposal.text, text=text, understanding=u, source="llm")
        if proposal.kind == "code":
            return self._propose_code(proposal.filename, proposal.code, "Here is the program I'd write")
        if proposal.kind == "command":
            cu = understand(proposal.text)
            ir, err, _ = self._try_compile(cu.text)
            if ir is None and hasattr(self.llm, "repair"):
                try:
                    fixed = self.llm.repair(text, proposal.text, str(err), context=self._context())
                except Exception:
                    fixed = None
                if fixed is not None and fixed.kind != "command":
                    return self._llm_outcome(fixed, text, u, original)
                if fixed is not None:
                    cu = understand(fixed.text)
                    ir, err, _ = self._try_compile(cu.text)
            if ir is None:
                return Outcome("reject", "The AI suggested something my compiler rejected, so I did nothing.",
                               text=proposal.text, understanding=cu, error=str(err), source="llm")
            cu.steps = u.steps + [Step("ai", "local AI model", text, cu.text)] + cu.steps
            cu.original = u.original
            if self.llm_autorun:
                return Outcome("ir", text=cu.text, ir=ir, understanding=cu, source="llm")
            self.pending = Pending("confirm_fix", suggestion=cu.text, question=f"Should I do this: “{cu.text}”?")
            return Outcome("clarify", self.pending.question, text=cu.text, ir=ir, understanding=cu, source="llm")
        return None

    def _propose_code(self, filename, code, intro):
        name = (filename or "").strip()
        if not SAFE_FILENAME.match(name):
            return Outcome("reject", f"The AI proposed an unsafe file name ({name!r}), so I did nothing.", source="llm")
        policy = self.agent.analyzer.policy
        if not policy.allowed(name):
            return Outcome("reject", f"{name} is outside the folders I'm allowed to change.", source="llm")
        lines = code.strip().splitlines()
        preview = "\n".join(lines[:25]) + ("\n..." if len(lines) > 25 else "")
        self.pending = Pending("confirm_code", base=name, suggestion=code.rstrip() + "\n",
                               question=f"{intro} ({name}, {len(lines)} lines). Should I save it?")
        return Outcome("clarify", self.pending.question, text=f"write {name}", source="llm",
                       results=[preview])

    def _fix_last_failure(self):
        if not self.last_failure:
            return Outcome("reject", "There is no failed script to fix yet.")
        path, error = self.last_failure
        if self.llm is None:
            return Outcome("reject", f"The last run of {path} failed: {error}. Fixing code needs the local AI model.")
        attempts = self.fix_attempts.get(path, 0)
        if attempts >= MAX_FIX_ATTEMPTS:
            return Outcome("reject", f"I've already tried to fix {path} {MAX_FIX_ATTEMPTS} times. "
                           "Please look at it yourself; I stopped to avoid looping.")
        try:
            with open(path, encoding="utf-8") as fh:
                code = fh.read()
        except OSError as e:
            return Outcome("reject", f"I couldn't read {path}: {e}")
        try:
            proposal = self.llm.fix_code(path, code, error)
        except Exception as e:
            return Outcome("reject", f"The local AI model is not available: {e}")
        self.fix_attempts[path] = attempts + 1
        if proposal.kind != "code" or not proposal.code:
            return Outcome("reject", "The AI could not propose a fix.")
        return self._propose_code(path, proposal.code, f"Fix attempt {attempts + 1} for {path}")

    def _context(self):
        return {"last_command": self.last_text, "last_app": self.last_app, "last_file": self.last_file,
                "recent": [o.text for o in self.history[-5:] if o.text]}

    def execute(self, outcome: Outcome) -> Outcome:
        if outcome.kind != "ir":
            return outcome
        if self.memory is not None:
            for op in outcome.ir:
                if op["op"] == "CHAT" and "phone" not in op["args"]:
                    phone = self.memory.contact(op["target"])
                    if phone:
                        op["args"]["phone"] = phone
        try:
            preset = outcome.message if outcome.source == "dictation" else ""
            outcome.results = self.agent.run_ir(outcome.ir)
            outcome.message = preset if outcome.source == "dictation" else summarize(outcome.ir, outcome.results)
        except ExecutionError as e:
            outcome.kind = "failed"
            outcome.error = str(e)
            outcome.results = list(getattr(e, "done", []) or [])
            reason = re.sub(r'^[A-Z_]+ failed: ', '', str(e))
            done = len(outcome.results)
            prefix = f"I completed {done} step{'s' if done != 1 else ''}, then stopped: " if done else "That didn't work: "
            outcome.message = prefix + reason
            return outcome
        self.last_text = outcome.text
        for op in outcome.ir:
            app = op["args"].get("app")
            if op["op"] in ("OPEN_APP", "SWITCH_APP", "NEW_DOCUMENT") and app:
                self.last_app = app
            if op["op"] == "CLOSE_APP" and app == self.last_app:
                self.last_app = None
            if op["op"] in ("CREATE_FILE", "OPEN_FILE", "CREATE_FOLDER", "WRITE_FILE", "APPEND_FILE", "RUN_SCRIPT"):
                self.last_file = op["target"]
        for op, result in zip([o for o in outcome.ir if o["op"] not in CONTROL], outcome.results):
            if op["op"] == "RUN_SCRIPT":
                self.last_failure = (op["target"], result.split("failed: ", 1)[1]) if " failed: " in result else None
        return outcome

    def handle(self, text, alternatives=None) -> Outcome:
        import time
        t0 = time.perf_counter()
        outcome = self.interpret(text, alternatives)
        outcome.timings["understand_ms"] = round((time.perf_counter() - t0) * 1000) - outcome.timings.get("ai_ms", 0)
        if outcome.kind == "ir":
            if self.on_progress is not None:
                self.on_progress(outcome)
            t1 = time.perf_counter()
            outcome = self.execute(outcome)
            outcome.timings["run_ms"] = round((time.perf_counter() - t1) * 1000)
        return self.record(text, outcome)

    def record(self, text, outcome):
        self.history.append(outcome)
        if self.memory is not None and outcome.kind not in ("memory",) and not is_sensitive(text):
            self.memory.log(text, outcome.text, outcome.kind)
        if self.speak and outcome.message:
            self.speak(outcome.message)
        return outcome


CONTROL = ("LABEL", "JUMP", "JUMP_IF_FALSE", "TEST", "LOOP_INIT", "LOOP_NEXT")


def summarize(ir, results):
    answers = [r for op, r in zip([o for o in ir if o["op"] not in
               ("LABEL", "JUMP", "JUMP_IF_FALSE", "TEST", "LOOP_INIT", "LOOP_NEXT")], results)
               if op["op"] in ("TELL", "CALCULATE")]
    if answers:
        return " ".join(answers)
    skipped = [r for r in results if r.startswith("Skipped")]
    if skipped:
        return skipped[0]
    if not results:
        return "Nothing to do."
    if len(results) == 1:
        return results[0]
    return f"Done, {len(results)} steps."
