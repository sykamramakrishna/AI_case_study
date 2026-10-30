import difflib
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSpec:
    name: str
    launch: str
    process: str
    title: str


APPS = {
    "word": {
        "aliases": ["microsoft word", "ms word", "winword", "word document"],
        "Windows": ("winword /w", "WINWORD.EXE", "Word"),
        "Darwin": ("Microsoft Word", "Microsoft Word", "Microsoft Word"),
        "Linux": ("libreoffice --writer", "soffice.bin", "Writer"),
    },
    "excel": {
        "aliases": ["microsoft excel", "ms excel", "spreadsheet"],
        "Windows": ("excel", "EXCEL.EXE", "Excel"),
        "Darwin": ("Microsoft Excel", "Microsoft Excel", "Microsoft Excel"),
        "Linux": ("libreoffice --calc", "soffice.bin", "Calc"),
    },
    "powerpoint": {
        "aliases": ["microsoft powerpoint", "ms powerpoint", "power point", "ppt"],
        "Windows": ("powerpnt", "POWERPNT.EXE", "PowerPoint"),
        "Darwin": ("Microsoft PowerPoint", "Microsoft PowerPoint", "Microsoft PowerPoint"),
        "Linux": ("libreoffice --impress", "soffice.bin", "Impress"),
    },
    "notepad": {
        "aliases": ["note pad", "notes app", "text editor", "textedit"],
        "Windows": ("notepad", "notepad.exe", "Notepad"),
        "Darwin": ("TextEdit", "TextEdit", "TextEdit"),
        "Linux": ("gedit", "gedit", "gedit"),
    },
    "chrome": {
        "aliases": ["google chrome", "browser", "web browser"],
        "Windows": ("chrome", "chrome.exe", "Google Chrome"),
        "Darwin": ("Google Chrome", "Google Chrome", "Google Chrome"),
        "Linux": ("google-chrome", "chrome", "Google Chrome"),
    },
    "edge": {
        "aliases": ["microsoft edge", "ms edge"],
        "Windows": ("msedge", "msedge.exe", "Edge"),
        "Darwin": ("Microsoft Edge", "Microsoft Edge", "Microsoft Edge"),
        "Linux": ("microsoft-edge", "msedge", "Microsoft Edge"),
    },
    "firefox": {
        "aliases": ["mozilla firefox", "mozilla"],
        "Windows": ("firefox", "firefox.exe", "Mozilla Firefox"),
        "Darwin": ("Firefox", "firefox", "Mozilla Firefox"),
        "Linux": ("firefox", "firefox", "Mozilla Firefox"),
    },
    "explorer": {
        "aliases": ["file explorer", "files", "file manager", "finder", "my computer", "this pc"],
        "Windows": ("explorer", "explorer.exe", "File Explorer"),
        "Darwin": ("Finder", "Finder", "Finder"),
        "Linux": ("nautilus", "nautilus", "Files"),
    },
    "vscode": {
        "aliases": ["vs code", "visual studio code", "code", "code editor"],
        "Windows": ("code", "Code.exe", "Visual Studio Code"),
        "Darwin": ("Visual Studio Code", "Code", "Visual Studio Code"),
        "Linux": ("code", "code", "Visual Studio Code"),
    },
    "terminal": {
        "aliases": ["command prompt", "cmd", "console", "shell", "powershell"],
        "Windows": ("cmd", "cmd.exe", "Command Prompt"),
        "Darwin": ("Terminal", "Terminal", "Terminal"),
        "Linux": ("gnome-terminal", "gnome-terminal-server", "Terminal"),
    },
    "calculator": {
        "aliases": ["calc", "calci"],
        "Windows": ("calc", "CalculatorApp.exe", "Calculator"),
        "Darwin": ("Calculator", "Calculator", "Calculator"),
        "Linux": ("gnome-calculator", "gnome-calculator", "Calculator"),
    },
    "paint": {
        "aliases": ["ms paint", "mspaint"],
        "Windows": ("mspaint", "mspaint.exe", "Paint"),
        "Darwin": ("Preview", "Preview", "Preview"),
        "Linux": ("pinta", "pinta", "Pinta"),
    },
    "whatsapp": {
        "aliases": ["whats app", "whatsapp desktop", "whatsapp app"],
        "Windows": ("whatsapp:", "WhatsApp.exe", "WhatsApp"),
        "Darwin": ("WhatsApp", "WhatsApp", "WhatsApp"),
        "Linux": ("whatsapp-for-linux", "whatsapp", "WhatsApp"),
        "web": "https://web.whatsapp.com",
    },
    "spotify": {
        "aliases": ["music"],
        "Windows": ("spotify", "Spotify.exe", "Spotify"),
        "Darwin": ("Spotify", "Spotify", "Spotify"),
        "Linux": ("spotify", "spotify", "Spotify"),
    },
}

WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp": "https://web.whatsapp.com",
    "wikipedia": "https://www.wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "leetcode": "https://leetcode.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "vtop": "https://vtop.vit.ac.in",
    "v top": "https://vtop.vit.ac.in",
}

APP_NOISE = {"the", "app", "application", "program", "window", "my", "file", "browser", "sheet", "sheets",
             "presentation", "software", "editor", "tool", "apps", "desktop"}

URL_RE = re.compile(
    r"^(https?://\S+|www\.\S+|[\w-]+(\.[\w-]+)*\.(com|org|net|in|edu|io|dev|ai|gov|co|me|app|tv|ac\.in|co\.in)(/\S*)?)$",
    re.IGNORECASE,
)
FILE_RE = re.compile(r"(^[~./\\])|([/\\])|(\.[A-Za-z0-9]{1,6}$)")


def _index():
    index = {}
    for name, spec in APPS.items():
        index[name] = name
        for alias in spec["aliases"]:
            index[alias] = name
            index[alias.replace(" ", "")] = name
    return index


APP_INDEX = _index()


def resolve_app(name):
    if not name:
        return None
    raw = name.lower().strip().replace("'", "")
    if raw in APP_INDEX:
        return APP_INDEX[raw]
    words = [w for w in raw.split() if w not in APP_NOISE]
    cleaned = " ".join(words)
    for candidate in (cleaned, cleaned.replace(" ", "")):
        if candidate in APP_INDEX:
            return APP_INDEX[candidate]
    if words and words[-1] == "document":
        return resolve_app(" ".join(words[:-1]))
    close = difflib.get_close_matches(cleaned.replace(" ", ""), list(APP_INDEX), n=1, cutoff=0.82)
    return APP_INDEX[close[0]] if close else None


def suggest_name(name, cutoff=0.6):
    if not name:
        return None
    raw = name.lower().replace("'", "").replace(" ", "")
    pool = {k.replace(" ", ""): APP_INDEX[k] for k in APP_INDEX}
    pool.update({k.replace(" ", ""): k for k in WEBSITES})
    close = difflib.get_close_matches(raw, list(pool), n=1, cutoff=cutoff)
    return pool[close[0]] if close else None


def resolve_website(name):
    if not name:
        return None
    raw = name.lower().strip().replace("'", "")
    if " " in raw and looks_like_url(raw.replace(" ", "")):
        raw = raw.replace(" ", "")
    for candidate in (raw, raw.replace(" ", "")):
        if candidate in WEBSITES:
            return WEBSITES[candidate]
    if looks_like_url(raw):
        return raw if raw.startswith("http") else "https://" + raw
    return None


def looks_like_url(text):
    return bool(text) and " " not in text.strip() and bool(URL_RE.match(text.strip()))


def looks_like_file(text):
    return bool(text) and bool(FILE_RE.search(text.strip())) and not looks_like_url(text)


def app_spec(name, system=None):
    system = system or platform.system()
    entry = APPS.get(name)
    if entry and system in entry:
        launch, process, title = entry[system]
        return AppSpec(name, launch, process, title)
    return AppSpec(name, name, name, name)


def running_processes():
    try:
        import psutil
        names = set()
        for proc in psutil.process_iter(["name"]):
            if proc.info.get("name"):
                names.add(proc.info["name"].lower())
        return names
    except ImportError:
        pass
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
            return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}
        if shutil.which("ps"):
            out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True).stdout
            return {line.strip().split("/")[-1].lower() for line in out.splitlines() if line.strip()}
    except OSError:
        pass
    return set()


def is_app_running(name, processes=None):
    processes = running_processes() if processes is None else processes
    spec = app_spec(name)
    target = spec.process.lower()
    return any(p == target or p.startswith(target.replace(".exe", "")) for p in processes)


KEY_ALIASES = {
    "playpause": "playpause", "nexttrack": "nexttrack", "prevtrack": "prevtrack", "volumemute": "volumemute",
    "control": "ctrl", "ctrl": "ctrl", "ctl": "ctrl",
    "alt": "alt", "option": "option", "shift": "shift",
    "windows": "win", "win": "win", "super": "win", "start": "win",
    "command": "command", "cmd": "command",
    "enter": "enter", "return": "enter",
    "escape": "esc", "esc": "esc",
    "tab": "tab", "space": "space", "spacebar": "space",
    "backspace": "backspace", "delete": "delete", "del": "delete",
    "insert": "insert", "home": "home", "end": "end",
    "pageup": "pageup", "pagedown": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "capslock": "capslock", "printscreen": "printscreen", "prtsc": "printscreen",
}
KEY_FILLER = {"key", "keys", "button", "the", "arrow", "and", "plus"}
KEY_PAIRS = {"page up", "page down", "caps lock", "print screen", "space bar", "back space"}


def normalize_keys(words):
    parts = []
    for word in words:
        parts.extend(p for p in str(word).lower().replace("+", " + ").split() if p != "+")
    joined = []
    i = 0
    while i < len(parts):
        pair = " ".join(parts[i:i + 2])
        if pair in KEY_PAIRS:
            joined.append(pair.replace(" ", ""))
            i += 2
            continue
        joined.append(parts[i])
        i += 1
    keys = []
    for word in joined:
        if word in KEY_ALIASES:
            keys.append(KEY_ALIASES[word])
        elif word in KEY_FILLER:
            continue
        elif len(word) == 1 and word.isalnum():
            keys.append(word)
        elif re.fullmatch(r"f([1-9]|1[0-2])", word):
            keys.append(word)
        else:
            raise ValueError(word)
    return keys
