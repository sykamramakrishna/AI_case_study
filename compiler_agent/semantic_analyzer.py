import os
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

from .ast_nodes import ActionNode, IfNode, ProgramNode, RepeatNode
from .calc import CalcError, calculate
from .policy import DEFAULT_POLICY
from .registry import APPS, suggest_name, looks_like_file, looks_like_url, normalize_keys, resolve_app, resolve_website

REQUIRED_ARGS = {
    "OPEN_APP": ["target"],
    "OPEN_URL": ["target"],
    "TYPE_TEXT": ["text"],
    "CLOSE_APP": ["target"],
    "SWITCH_APP": ["target"],
    "CREATE_FILE": ["target"],
    "DELETE_FILE": ["target"],
    "SEARCH": ["text"],
    "PRESS": ["target"],
    "WAIT": ["number"],
    "SCROLL": ["target"],
    "CLICK": ["text"],
    "CALCULATE": ["text"],
    "CHAT": ["text"],
    "PLAY": ["text"],
    "TELL": ["target"],
}

KNOWN_APPS = set(APPS)
MAX_REPEAT = 50
MAX_WAIT_SECONDS = 120
DESTRUCTIVE = {"DELETE_FILE", "CLOSE_APP", "RUN_SCRIPT", "RUN_TESTS"}
RUN_WORDS = {"run", "execute"}
WAIT_UNITS = {None: 1, "second": 1, "seconds": 1, "sec": 1, "secs": 1, "minute": 60, "minutes": 60, "min": 60}
VOLUME_WORDS = {"mute": "mute", "unmute": "unmute", "increase": "up", "raise": "up", "decrease": "down", "lower": "down"}
CLICK_SUFFIXES = {"button", "icon", "link", "option", "tab", "menu"}
DOCUMENT_APPS = {"word", "excel", "powerpoint", "notepad"}
DOCUMENT_NOISE = {"document", "doc", "docs", "sheet", "workbook", "presentation", "blank", "empty", "page"}
TITLE_WORDS = {"title", "heading"}
NO_TARGET_VERBS = {"SCREENSHOT", "COPY", "MINIMIZE", "MAXIMIZE", "LOCK"}
FOLDER_WORDS = {"folder", "directory", "dir"}
BULK_WORDS = {"everything", "all", "every", "files", "anything"}
FILE_TYPES = {"text": ".txt", "txt": ".txt", "python": ".py", "html": ".html", "web": ".html", "csv": ".csv",
              "markdown": ".md", "json": ".json", "javascript": ".js", "java": ".java", "css": ".css"}
TELL_TOPICS = {"time": "time", "date": "date", "day": "date", "today": "date"}
SEARCH_SITES = {"youtube": "youtube", "google": "google"}
TAB_WORDS = {"tab", "tabs"}
BROWSER_WORDS = {"google": "chrome", "chrome": "chrome", "browser": "chrome", "edge": "edge", "firefox": "firefox"}


class SemanticError(Exception):
    def __init__(self, message, missing=None, verb=None, word=None):
        super().__init__(message)
        self.missing = missing
        self.verb = verb
        self.word = word


@dataclass
class State:
    clipboard: Optional[str] = None
    files: Dict[str, bool] = field(default_factory=dict)
    running: Dict[str, bool] = field(default_factory=dict)
    focused: Optional[str] = None

    def copy(self):
        return State(self.clipboard, dict(self.files), dict(self.running), self.focused)

    def merge(self, other):
        if self.clipboard == other.clipboard:
            clip = self.clipboard
        elif self.clipboard is None or other.clipboard is None:
            clip = None
        else:
            clip = "MIXED"
        files = {k: v for k, v in self.files.items() if other.files.get(k) == v}
        running = {k: v for k, v in self.running.items() if other.running.get(k) == v}
        focused = self.focused if self.focused == other.focused else None
        return State(clip, files, running, focused)


def normalize_path(path):
    return os.path.normpath(os.path.expanduser(path.strip().strip('"').strip("'")))


class SemanticAnalyzer:
    def __init__(self, known_apps=None, policy=None):
        self.known_apps = set(known_apps) if known_apps else KNOWN_APPS
        self.policy = policy or DEFAULT_POLICY
        self.warnings = []
        self.final_state = State()

    def analyze(self, program: ProgramNode, initial_clipboard=None) -> ProgramNode:
        self.warnings = []
        state = State(clipboard=initial_clipboard)
        self.final_state = self._block(program.statements, state)
        return program

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def _block(self, statements, state):
        for stmt in statements:
            state = self._statement(stmt, state)
        return state

    def _statement(self, stmt, state):
        if isinstance(stmt, ActionNode):
            return self._action(stmt, state)
        if isinstance(stmt, IfNode):
            then_in, else_in = self._condition(stmt.condition, state)
            then_out = self._block(stmt.then_body, then_in)
            else_out = self._block(stmt.else_body, else_in)
            if stmt.condition.static is True:
                return then_out
            if stmt.condition.static is False:
                return else_out
            return then_out.merge(else_out)
        if isinstance(stmt, RepeatNode):
            if not 1 <= stmt.count <= MAX_REPEAT:
                raise SemanticError(f"'repeat {stmt.count} times' is out of range: allowed 1 to {MAX_REPEAT} times")
            out = self._block(stmt.body, state.copy())
            if stmt.count > 1:
                out = self._block(stmt.body, out.copy())
            return out
        raise SemanticError(f"Unknown statement {stmt!r}")

    def _condition(self, cond, state):
        then_state, else_state = state.copy(), state.copy()
        if cond.kind == "EXISTS":
            key = normalize_path(cond.subject)
            known = state.files.get(key)
            then_state.files[key] = not cond.negated
            else_state.files[key] = cond.negated
        else:
            app = resolve_app(cond.subject) or cond.subject.lower()
            if app not in self.known_apps:
                self._warn(f"'{cond.subject}' is not a registered app; its process name will be guessed")
            cond.app = app
            known = state.running.get(app)
            then_state.running[app] = not cond.negated
            else_state.running[app] = cond.negated
        value = None if known is None else (known != cond.negated)
        if cond.analyzed and cond.static != value:
            cond.static = None
        else:
            cond.static = value
        cond.analyzed = True
        return then_state, else_state

    def _fail(self, action, message, missing=None):
        raise SemanticError(
            f"Step {action.index} ('{action.word or action.verb.lower()}'): {message}",
            missing=missing, verb=action.verb, word=action.word,
        )

    def _check_required_args(self, action):
        for required in REQUIRED_ARGS.get(action.verb, []):
            if required == "target" and not action.target:
                if action.verb == "PRESS":
                    self._fail(action, "say which key to press, e.g. 'press enter' or 'press control s'.", missing="target")
                if action.verb == "SCROLL":
                    self._fail(action, "say a direction, e.g. 'scroll down'.", missing="target")
                self._fail(action, "missing a target (e.g. an app or file name).", missing="target")
            if required == "text" and "text" not in action.args:
                if action.verb == "CLICK":
                    self._fail(action, "say what to click, e.g. 'click on Save'.", missing="text")
                if action.verb == "SEARCH":
                    self._fail(action, "say what to search for, e.g. 'search for compiler design notes'.", missing="text")
                self._fail(action, 'missing text to type, e.g. type "hello world" or just: type hello world.', missing="text")
            if required == "number" and "number" not in action.args:
                self._fail(action, "missing a duration, e.g. 'wait 2 seconds'.", missing="number")

    def _resolve_app_target(self, action, state, must_be_app=False):
        target = action.target
        app = resolve_app(target)
        if app:
            action.args["app"] = app
            action.target = app
            return app
        if must_be_app and looks_like_file(target):
            self._fail(action, f"'{target}' looks like a file, not an application.")
        if action.verb in ("CLOSE_APP", "SWITCH_APP"):
            hint = suggest_name(target)
            extra = f" Did you mean {hint}?" if hint else ""
            self._fail(action, f"I don't know an app called '{target}', so I won't touch it.{extra}",
                       missing="unknown_app")
        action.args["app"] = target.lower()
        action.args["unregistered_app"] = True
        self._warn(f"'{target}' is not a registered app; it will be launched by name")
        return target.lower()

    def _action(self, action, state):
        if action.verb == "OPEN_URL" and action.target and resolve_app(action.target) and not resolve_website(action.target):
            action.verb = "SWITCH_APP"
        if action.verb == "VOLUME" and not action.target and action.word in VOLUME_WORDS:
            action.target = VOLUME_WORDS[action.word]
        if action.verb == "CLICK" and "text" not in action.args and action.target:
            action.args["text"] = action.target
            action.target = None
        if action.verb == "SEARCH" and "text" not in action.args and action.target:
            action.args["text"] = action.target
            action.target = None
        if action.verb in NO_TARGET_VERBS:
            action.target = None
        self._check_required_args(action)
        handler = getattr(self, f"_check_{action.verb.lower()}", None)
        if handler:
            handler(action, state)
        if action.verb in DESTRUCTIVE:
            action.args["destructive"] = True
        return state

    def _guard_path(self, action, path):
        if not self.policy.allowed(path):
            self._fail(action, f"'{path}' is outside the folders I'm allowed to change ({self.policy.describe_roots()}).")

    def _check_open_app(self, action, state):
        target = action.target
        if action.word in RUN_WORDS and target.lower() in ("tests", "the tests", "test", "unit tests", "all tests", "all the tests"):
            action.verb = "RUN_TESTS"
            action.target = "."
            return
        if action.word in RUN_WORDS and target.lower().endswith(".py"):
            path = normalize_path(target)
            self._guard_path(action, path)
            if state.files.get(path) is False:
                self._fail(action, f"'{target}' was deleted earlier in this command.")
            action.verb = "RUN_SCRIPT"
            return
        app = resolve_app(target)
        if app:
            action.args["app"] = app
            action.target = app
            state.running[app] = True
            state.focused = app
            return
        url = resolve_website(target)
        if url:
            action.verb = "OPEN_URL"
            action.args["url"] = url
            action.target = url
            state.focused = None
            return
        if looks_like_file(target):
            path = normalize_path(target)
            if state.files.get(path) is False:
                self._fail(action, f"'{target}' was deleted earlier in this command.")
            action.verb = "OPEN_FILE"
            state.focused = None
            return
        self._resolve_app_target(action, state)
        state.running[action.args["app"]] = True
        state.focused = action.args["app"]

    def _check_open_url(self, action, state):
        url = resolve_website(action.target)
        if not url:
            self._fail(action, f"'{action.target}' is not a website I recognise. Try a full address like example.com.")
        action.args["url"] = url
        action.target = url
        state.focused = None

    def _close_tabs(self, action, state):
        words = action.target.lower().split()
        if not any(w in TAB_WORDS for w in words):
            return False
        browser = next((BROWSER_WORDS[w] for w in words if w in BROWSER_WORDS), None)
        if "all" in words or "every" in words or "tabs" in words:
            action.target = browser or "chrome"
            return False
        action.verb = "PRESS"
        action.target = "ctrl+w"
        action.args["keys"] = ["ctrl", "w"]
        return True

    def _check_close_app(self, action, state):
        if self._close_tabs(action, state):
            return
        app = self._resolve_app_target(action, state, must_be_app=True)
        state.running[app] = False
        if state.focused == app:
            state.focused = None

    def _check_switch_app(self, action, state):
        app = self._resolve_app_target(action, state, must_be_app=True)
        if state.running.get(app) is False:
            self._fail(action, f"cannot switch to {action.target}: it is closed earlier in this command.")
        state.focused = app

    def _check_screenshot(self, action, state):
        state.clipboard = "SCREENSHOT"

    def _check_copy(self, action, state):
        state.clipboard = "COPY"

    def _check_select(self, action, state):
        if action.target and action.target.lower() not in ("all", "everything"):
            self._fail(action, "only 'select all' is supported.")
        action.target = "all"

    def _target_app(self, action, state):
        if action.target and action.verb == "TYPE_TEXT" and looks_like_file(action.target) and not resolve_app(action.target):
            path = normalize_path(action.target)
            self._guard_path(action, path)
            action.verb = "APPEND_FILE"
            state.files[path] = True
            return
        if action.target:
            app = self._resolve_app_target(action, state, must_be_app=True)
            if state.running.get(app) is False:
                self._fail(action, f"{action.target} is closed earlier in this command.")
            state.focused = app

    def _check_paste(self, action, state):
        if state.clipboard is None:
            self._fail(action, "nothing to paste — no prior 'copy' or 'take a screenshot' in this command.")
        action.args["source"] = state.clipboard
        self._target_app(action, state)

    def _check_type_text(self, action, state):
        if not action.args["text"].strip():
            self._fail(action, "the text to type is empty.")
        self._target_app(action, state)

    def _new_document(self, action, state):
        words = action.target.split()
        app = resolve_app(words[0])
        if app not in DOCUMENT_APPS or looks_like_file(action.target):
            return False
        rest = [w for w in words[1:] if w.lower() not in DOCUMENT_NOISE]
        cut = next((i for i, w in enumerate(rest) if w.lower() in TITLE_WORDS), None)
        has_title = cut is not None
        name_words = rest if cut is None else rest[:cut]
        title_words = [] if cut is None else [w for w in rest[cut + 1:] if w.lower() not in TITLE_WORDS]
        name = " ".join(name_words) or None
        text = action.args.pop("text", None)
        title = text or " ".join(title_words) or None
        if text and not has_title and not name:
            name, title = text, None
        action.verb = "NEW_DOCUMENT"
        action.target = app
        action.args["app"] = app
        if title:
            action.args["title"] = title
        if name:
            action.args["name"] = name
        state.running[app] = True
        state.focused = app
        return True

    def _check_create_file(self, action, state):
        words = action.target.split()
        if words[0].lower() in FOLDER_WORDS:
            name = " ".join(words[1:])
            if not name:
                self._fail(action, "say the folder name, e.g. 'create folder projects'.", missing="target")
            self._guard_path(action, normalize_path(name))
            action.verb = "CREATE_FOLDER"
            action.target = name
            return
        if self._new_document(action, state):
            return
        if not looks_like_file(action.target):
            self._fail(action, f"'{action.target}' isn't a file name. Say the name with its extension, like notes.txt.",
                       missing="filename")
        if looks_like_url(action.target):
            self._fail(action, f"'{action.target}' looks like a website, not a file name.")
        path = normalize_path(action.target)
        self._guard_path(action, path)
        if state.files.get(path) is True:
            self._warn(f"'{action.target}' is created more than once; the extra create does nothing")
        state.files[path] = True

    def _check_delete_file(self, action, state):
        target = action.target
        if any(w.lower() in BULK_WORDS for w in target.split()):
            self._fail(action, "deleting several files at once is not allowed; name one file.")
        if any(ch in target for ch in "*?"):
            self._fail(action, "wildcards are not allowed in delete, name one file.")
        path = normalize_path(target)
        if path in (".", "..", os.path.expanduser("~"), os.sep) or os.path.isdir(path):
            self._fail(action, f"'{target}' is a folder; only single files can be deleted.")
        self._guard_path(action, path)
        if state.files.get(path) is False:
            self._fail(action, f"'{target}' was already deleted earlier in this command.")
        state.files[path] = False

    def _check_open_file(self, action, state):
        pass

    def _check_search(self, action, state):
        text = action.args["text"].strip()
        low = text.lower()
        site = None
        for word, name in SEARCH_SITES.items():
            for prefix in (f"{word} for ", f"on {word} for ", f"in {word} for "):
                if low.startswith(prefix):
                    site, text = name, text[len(prefix):]
                    break
            for suffix in (f" on {word}", f" in {word}"):
                if site is None and low.endswith(suffix):
                    site, text = name, text[: -len(suffix)]
            if site:
                break
        if not text.strip():
            self._fail(action, "say what to search for.", missing="text")
        action.args["text"] = text.strip()
        if site and site != "google":
            action.args["site"] = site
        state.focused = None

    def _check_tell(self, action, state):
        topic = TELL_TOPICS.get(action.target.lower().split()[-1])
        if not topic:
            self._fail(action, "I can tell the time or the date.")
        action.target = topic

    def _check_play(self, action, state):
        query = action.args.pop("text").strip()
        query = re.sub(r"\s+(?:on|in|from)\s+youtube$", "", query, flags=re.I)
        query = re.sub(r"^(?:the\s+)?(?:song|video|music)\s+(?:called|named)?\s*", "", query, flags=re.I).strip(" ,.")
        if not query:
            self._fail(action, "say what to play, e.g. 'play Kesariya song'.", missing="text")
        action.target = None
        action.args = {"query": query, "site": "youtube"}
        state.focused = None

    def _check_chat(self, action, state):
        text = action.args.pop("text").strip()
        text = re.sub(r"^(?:with|to)\s+", "", text, flags=re.I)
        parts = re.split(r"\s+(?:saying|that says|and say|and send|message)\s+", text, maxsplit=1, flags=re.I)
        contact = re.sub(r"\s+(?:on|in)\s+(?:whats\s?app)$", "", parts[0], flags=re.I).strip(" ,.")
        contact = re.sub(r"'s$", "", contact)
        message = parts[1].strip() if len(parts) > 1 else None
        if not contact or contact.lower() in ("whatsapp", "him", "her", "them", "someone"):
            self._fail(action, "say who to chat with, e.g. 'open WhatsApp chat with Rahul'.", missing="text")
        if len(contact.split()) > 4:
            self._fail(action, f"'{contact}' doesn't look like a contact name.")
        action.target = contact
        action.args = {"app": "whatsapp"}
        if message:
            action.args["message"] = message
            action.args["destructive"] = True

    def _check_calculate(self, action, state):
        try:
            expr, value = calculate(action.args["text"])
        except CalcError as e:
            self._fail(action, str(e))
        action.args = {"expr": expr, "value": value}

    def _check_press(self, action, state):
        try:
            keys = normalize_keys(action.target.split())
        except ValueError as e:
            self._fail(action, f"unknown key '{e}'. Try names like enter, tab, control, alt, shift, escape, f5.")
        if not keys:
            self._fail(action, "say which key to press.")
        action.args["keys"] = keys
        action.target = "+".join(keys)

    def _check_wait(self, action, state):
        unit = action.target.lower() if action.target else None
        if unit not in WAIT_UNITS:
            self._fail(action, f"unknown time unit '{action.target}', use seconds or minutes.")
        seconds = action.args.pop("number") * WAIT_UNITS[unit]
        if not 0 < seconds <= MAX_WAIT_SECONDS:
            self._fail(action, f"wait must be between 1 and {MAX_WAIT_SECONDS} seconds.")
        action.args["seconds"] = seconds
        action.target = None

    def _check_scroll(self, action, state):
        direction = action.target.lower()
        if direction not in ("up", "down"):
            self._fail(action, "scroll direction must be 'up' or 'down'.")
        action.target = direction
        action.args["amount"] = action.args.pop("number", 5)

    def _check_volume(self, action, state):
        if action.target not in ("up", "down", "mute", "unmute"):
            self._fail(action, "say 'volume up', 'volume down', 'mute' or 'unmute'.")

    def _check_click(self, action, state):
        words = action.args["text"].strip().split()
        while len(words) > 1 and words[-1].lower() in CLICK_SUFFIXES:
            words.pop()
        action.args["text"] = re.sub(r"\s+", " ", " ".join(words))
        state.focused = None

    def _check_save_file(self, action, state):
        if action.target and looks_like_url(action.target):
            self._fail(action, f"'{action.target}' is not a valid file name.")
        if action.target:
            state.files[normalize_path(action.target)] = True
