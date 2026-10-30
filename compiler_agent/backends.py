import io
import os
import platform
import re
import sys
import shlex
import shutil
import subprocess
import time
import webbrowser
from urllib.parse import quote_plus

from .registry import app_spec, is_app_running, running_processes

SEARCH_URL = "https://www.google.com/search?q="
SITE_SEARCH = {
    None: SEARCH_URL,
    "youtube": "https://www.youtube.com/results?search_query=",
}


def search_url(query, site=None):
    return SITE_SEARCH.get(site, SEARCH_URL) + quote_plus(query)


class BackendError(Exception):
    pass


def first_youtube_video(query, timeout=5):
    import urllib.request
    url = search_url(query, "youtube")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "ignore")
    except Exception:
        return None
    return parse_first_video(html)


def parse_first_video(html):
    for pattern in (r'"videoRenderer":\{"videoId":"([\w-]{11})"', r'"videoId":"([\w-]{11})"', r"/watch\?v=([\w-]{11})"):
        m = re.search(pattern, html or "")
        if m:
            return m.group(1)
    return None


def explain_python_error(stderr):
    lines = [l for l in (stderr or "").strip().splitlines() if l.strip()]
    if not lines:
        return "it exited with an error but printed no message"
    last = lines[-1].strip()
    where = None
    for line in reversed(lines):
        m = re.search(r'File "([^"]+)", line (\d+)', line)
        if m:
            where = (os.path.basename(m.group(1)), int(m.group(2)))
            break
    hints = {
        "NameError": "a variable or function is used before it is defined or is misspelled",
        "SyntaxError": "the code is not valid Python, often a missing colon, bracket or quote",
        "IndentationError": "the indentation (spaces at the start of a line) is inconsistent",
        "ModuleNotFoundError": "a library is not installed; install it with pip",
        "ImportError": "an import failed; check the module and name",
        "TypeError": "a value of the wrong type was passed to an operation or function",
        "ValueError": "a function got a value it cannot handle",
        "ZeroDivisionError": "the code divides by zero",
        "IndexError": "a list index is past the end of the list",
        "KeyError": "a dictionary key does not exist",
        "FileNotFoundError": "the script tried to open a file that does not exist",
        "AttributeError": "an object does not have the attribute or method being used",
    }
    kind = last.split(":")[0].strip()
    hint = hints.get(kind, "")
    place = f" at line {where[1]} of {where[0]}" if where else ""
    return f"{last}{place}" + (f" ({hint})" if hint else "")


def run_python(args, cwd, timeout, limit):
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise BackendError(f"stopped after {timeout} seconds (it may contain an infinite loop or wait for input)")
    out = (proc.stdout or "")[-limit:]
    err = (proc.stderr or "")[-limit:]
    return proc.returncode, out, err


def expand(path):
    return os.path.abspath(os.path.expanduser(path))


class DryRunBackend:
    tag = "[DRY RUN]"

    def __init__(self, screenshot_dir="./screenshots"):
        self.screenshot_dir = screenshot_dir
        self.created = set()
        self.deleted = set()
        self.opened = set()
        self.closed = set()
        self._processes = None

    def _procs(self):
        if self._processes is None:
            self._processes = running_processes()
        return self._processes

    def open_app(self, app, new=False):
        already = not new and self.is_running(app)
        self.opened.add(app)
        self.closed.discard(app)
        if already:
            return f"Would switch to {app} (already open)"
        return f"Would open application: {app}"

    def play_youtube(self, query):
        return f"Would play the top YouTube result for '{query}'"

    def close_app(self, app):
        self.closed.add(app)
        self.opened.discard(app)
        return f"Would close application: {app}"

    def focus_app(self, app):
        return f"Would bring {app} to the front"

    def is_running(self, app):
        if app in self.opened:
            return True
        if app in self.closed:
            return False
        return is_app_running(app, self._procs())

    def open_url(self, url):
        return f"Would open {url} in the default browser"

    def open_file(self, path):
        return f"Would open file: {path}"

    def search(self, query, site=None):
        where = "YouTube" if site == "youtube" else "the web"
        return f"Would search {where} for '{query}' ({search_url(query, site)})"

    def create_folder(self, path):
        full = expand(path)
        if os.path.isfile(full):
            raise BackendError(f"'{path}' already exists as a file")
        self.created.add(full)
        return f"Would create folder: {path}"

    def window(self, action):
        return f"Would {action} the active window"

    def whatsapp_chat(self, contact, message, phone=None):
        tail = f" and send “{message}”" if message else ""
        how = f"open the chat with {contact} (+{phone}) directly" if phone else f"search for {contact}'s chat"
        return f"Would open WhatsApp and {how}{tail}"

    def write_file(self, path, text):
        full = expand(path)
        self.created.add(full)
        self.deleted.discard(full)
        return f"Would write {len(text.splitlines())} lines to {path}"

    def append_file(self, path, text):
        full = expand(path)
        self.created.add(full)
        self.deleted.discard(full)
        return f"Would write '{text}' into {path}"

    def run_script(self, path, timeout, limit):
        if not self.file_exists(path):
            raise BackendError(f"cannot run '{path}': no such file")
        return f"Would run: python {path} (timeout {timeout}s)"

    def run_tests(self, folder, timeout, limit):
        return f"Would run the tests in {os.path.abspath(folder)} (timeout {timeout}s)"

    def lock(self):
        return "Would lock the computer"

    def screenshot(self, path):
        return f"Would take a screenshot, save it to {path} and copy it to the clipboard"

    def type_text(self, text):
        return f"Would type: '{text}'"

    def press(self, keys):
        return f"Would press {'+'.join(keys)}"

    def copy(self):
        return "Would send Ctrl+C to copy current selection"

    def paste(self, target):
        return f"Would paste clipboard contents into: {target or 'active window'}"

    def select_all(self):
        return "Would send Ctrl+A to select everything"

    def save(self, filename):
        return f"Would save the current file{' as ' + filename if filename else ''}"

    def file_exists(self, path):
        full = expand(path)
        if full in self.created:
            return True
        if full in self.deleted:
            return False
        return os.path.exists(full)

    def create_file(self, path):
        full = expand(path)
        self.created.add(full)
        self.deleted.discard(full)
        return f"Would create file: {path}"

    def delete_file(self, path):
        if not self.file_exists(path):
            raise BackendError(f"cannot delete '{path}': no such file")
        full = expand(path)
        self.deleted.add(full)
        self.created.discard(full)
        return f"Would delete file: {path}"

    def wait(self, seconds):
        return f"Would wait {seconds} second(s)"

    def scroll(self, direction, amount):
        return f"Would scroll {direction} by {amount}"

    def volume(self, action):
        return f"Would change volume: {action}"

    def click_text(self, label):
        return f"Would find '{label}' on screen with OCR and click it"


OWN_TITLES = ("Compiler Voice Assistant", "Vaani Voice Compiler")


class FocusGuard:
    def __init__(self):
        import threading
        self.last_external = None
        self.available = False
        self._own_pids = set()
        try:
            import win32gui
            import win32process
            self.win32gui = win32gui
            self.win32process = win32process
            self.available = True
        except ImportError:
            return
        self._own_pids = self._ancestor_pids()
        threading.Thread(target=self._watch, daemon=True).start()

    @staticmethod
    def _ancestor_pids():
        pids = {os.getpid()}
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            for parent in proc.parents():
                pids.add(parent.pid)
        except Exception:
            pass
        return pids

    def is_own(self, hwnd):
        if not hwnd:
            return True
        try:
            title = self.win32gui.GetWindowText(hwnd)
            if any(t in title for t in OWN_TITLES):
                return True
            _, pid = self.win32process.GetWindowThreadProcessId(hwnd)
            return pid in self._own_pids
        except Exception:
            return True

    def _watch(self):
        while True:
            try:
                hwnd = self.win32gui.GetForegroundWindow()
                if hwnd and not self.is_own(hwnd) and self.win32gui.GetWindowText(hwnd):
                    self.last_external = hwnd
            except Exception:
                pass
            time.sleep(0.3)

    def activate(self, hwnd, press_alt):
        import win32con
        if self.win32gui.IsIconic(hwnd):
            self.win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        for _ in range(3):
            press_alt()
            try:
                self.win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            time.sleep(0.25)
            if self.win32gui.GetForegroundWindow() == hwnd:
                return True
        return False

    def ensure_external(self, press_alt):
        if not self.available:
            return None
        current = self.win32gui.GetForegroundWindow()
        if current and not self.is_own(current):
            return current
        target = self.last_external
        if not target or not self.win32gui.IsWindow(target):
            raise BackendError("I don't know which window to use. Click the app you want "
                               "(for example Notepad or the browser) once, then say the command again")
        if not self.activate(target, press_alt):
            raise BackendError(f"couldn't bring '{self.win32gui.GetWindowText(target)}' to the front")
        return target

    def centre(self, hwnd):
        left, top, right, bottom = self.win32gui.GetWindowRect(hwnd)
        return (left + right) // 2, (top + bottom) // 2


class LiveBackend:
    tag = "[LIVE]"

    def __init__(self, screenshot_dir="./screenshots"):
        self._pg = None
        self._clip = None
        self._grab = None
        self.screenshot_dir = screenshot_dir
        self.system = platform.system()
        self.mod = "command" if self.system == "Darwin" else "ctrl"
        self.focus = FocusGuard() if self.system == "Windows" else None

    def _target(self):
        if self.focus is None:
            return None
        return self.focus.ensure_external(lambda: self.pyautogui.press("alt"))

    @property
    def pyautogui(self):
        if self._pg is None:
            try:
                import pyautogui
            except Exception as e:
                raise BackendError(f"keyboard/mouse control is unavailable ({type(e).__name__}: {e}). "
                                   "Run: pip install pyautogui") from e
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._pg = pyautogui
        return self._pg

    @property
    def pyperclip(self):
        if self._clip is None:
            try:
                import pyperclip
            except Exception as e:
                raise BackendError("clipboard access needs pyperclip: pip install pyperclip") from e
            self._clip = pyperclip
        return self._clip

    @property
    def ImageGrab(self):
        if self._grab is None:
            try:
                from PIL import ImageGrab
            except Exception as e:
                raise BackendError("screenshots need Pillow: pip install Pillow") from e
            self._grab = ImageGrab
        return self._grab

    def _run(self, args, **kw):
        return subprocess.run(args, capture_output=True, text=True, **kw)

    def _osascript(self, script):
        return self._run(["osascript", "-e", script])

    def open_app(self, app, new=False):
        spec = app_spec(app, self.system)
        if not new and self._find_window(spec) is not None:
            try:
                self.focus_app(app)
                return f"Switched to {app} (it was already open)"
            except BackendError:
                pass
        if spec.launch.endswith(":") and self.system == "Windows" and not self._uri_handler_exists(spec.launch[:-1]):
            from .registry import APPS
            web = APPS.get(app, {}).get("web")
            if web:
                webbrowser.open(web)
                return f"{app} desktop app isn't installed, so I opened {web}"
            raise BackendError(f"{app} is not installed")
        try:
            if self.system == "Windows":
                subprocess.Popen(f'start "" {spec.launch}', shell=True)
            elif self.system == "Darwin":
                result = self._run(["open", "-a", spec.launch])
                if result.returncode != 0:
                    raise BackendError(result.stderr.strip() or f"could not open {app}")
            else:
                subprocess.Popen(shlex.split(spec.launch), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError as e:
            raise BackendError(f"'{spec.launch}' is not installed or not on PATH") from e
        if not self._wait_for_window(spec):
            return f"Started {app}, but its window did not appear within 8 seconds"
        return f"Opened {app}"

    def _wait_for_window(self, spec, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._find_window(spec) is not None:
                time.sleep(0.25)
                return True
            time.sleep(0.2)
        return False

    def _windows_list(self):
        import win32gui
        import win32process
        try:
            import psutil
        except ImportError:
            psutil = None
        found = []
        names = self.__dict__.setdefault("_exe_names", {})
        if len(names) > 500:
            names.clear()

        def visit(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            exe = ""
            if psutil is not None:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    exe = names.get(pid)
                    if exe is None:
                        exe = names[pid] = psutil.Process(pid).name()
                except Exception:
                    exe = ""
            found.append((hwnd, title, exe))

        win32gui.EnumWindows(visit, None)
        return found

    def _find_window(self, spec):
        if self.system == "Windows":
            try:
                windows = self._windows_list()
            except ImportError:
                return None
            proc = spec.process.lower()
            stem = proc[:-4] if proc.endswith(".exe") else proc
            by_exe = [w for w in windows if w[2].lower() == proc or (len(stem) > 3 and w[2].lower().startswith(stem + "."))]
            if by_exe:
                return by_exe[0]
            ends = [w for w in windows if w[1].lower().endswith(spec.title.lower())]
            if ends:
                return ends[0]
            contains = [w for w in windows if spec.title.lower() in w[1].lower()]
            return contains[0] if contains else None
        if self.system == "Darwin":
            return spec.name if self.is_running(spec.name) else None
        if shutil.which("wmctrl"):
            out = self._run(["wmctrl", "-l"]).stdout
            for line in out.splitlines():
                if spec.title.lower() in line.lower():
                    return line.split()[0]
            return None
        return spec.name if self.is_running(spec.name) else None

    def focus_app(self, app):
        spec = app_spec(app, self.system)
        if self.system == "Windows":
            try:
                import win32con
                import win32gui
            except ImportError as e:
                raise BackendError("Switching windows on Windows needs pywin32: pip install pywin32") from e
            window = self._find_window(spec)
            if window is None:
                raise BackendError(f"no open window found for {app}; open it first")
            hwnd = window[0]
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            self.pyautogui.press("alt")
            win32gui.SetForegroundWindow(hwnd)
        elif self.system == "Darwin":
            result = self._osascript(f'tell application "{spec.launch}" to activate')
            if result.returncode != 0:
                raise BackendError(f"could not switch to {app}: {result.stderr.strip()}")
        else:
            if shutil.which("wmctrl"):
                result = self._run(["wmctrl", "-a", spec.title])
            elif shutil.which("xdotool"):
                result = self._run(["xdotool", "search", "--name", spec.title, "windowactivate"])
            else:
                raise BackendError("switching windows on Linux needs wmctrl or xdotool installed")
            if result.returncode != 0:
                raise BackendError(f"no open window found for {app}; open it first")
        time.sleep(0.4)
        return f"Switched to {app}"

    def close_app(self, app):
        spec = app_spec(app, self.system)
        if self.system == "Windows":
            self._run(["taskkill", "/IM", spec.process])
        elif self.system == "Darwin":
            self._osascript(f'tell application "{spec.launch}" to quit')
        else:
            self._run(["pkill", "-f", spec.process])
        return f"Closed {app}"

    def is_running(self, app):
        return is_app_running(app)

    def open_url(self, url):
        webbrowser.open(url)
        time.sleep(0.5)
        return f"Opened {url}"

    def open_file(self, path):
        full = expand(path)
        if not os.path.exists(full):
            raise BackendError(f"no such file: {path}")
        if self.system == "Windows":
            os.startfile(full)
        elif self.system == "Darwin":
            subprocess.Popen(["open", full])
        else:
            subprocess.Popen(["xdg-open", full], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        return f"Opened {path}"

    def search(self, query, site=None):
        webbrowser.open(search_url(query, site))
        time.sleep(0.5)
        where = "YouTube" if site == "youtube" else "the web"
        return f"Searched {where} for '{query}'"

    def create_folder(self, path):
        full = expand(path)
        if os.path.isfile(full):
            raise BackendError(f"'{path}' already exists as a file")
        existed = os.path.isdir(full)
        os.makedirs(full, exist_ok=True)
        if not os.path.isdir(full):
            raise BackendError(f"could not create folder '{path}'")
        return f"Folder {path} already existed" if existed else f"Created folder {path}"

    def write_file(self, path, text):
        full = expand(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".compiler-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, full)
        with open(full, encoding="utf-8") as fh:
            if fh.read() != text:
                raise BackendError(f"could not verify {path} was written")
        return f"Wrote {len(text.splitlines())} lines to {path}"

    def append_file(self, path, text):
        full = expand(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        existing = ""
        if os.path.exists(full):
            with open(full, encoding="utf-8", errors="replace") as fh:
                existing = fh.read()
        prefix = "\n" if existing and not existing.endswith("\n") else ""
        with open(full, "a", encoding="utf-8") as fh:
            fh.write(prefix + text + "\n")
        with open(full, encoding="utf-8", errors="replace") as fh:
            if not fh.read().endswith(text + "\n"):
                raise BackendError(f"could not verify the text was written to {path}")
        return f"Wrote '{text}' into {path}"

    def run_script(self, path, timeout, limit):
        full = expand(path)
        if not os.path.isfile(full):
            raise BackendError(f"cannot run '{path}': no such file")
        code, out, err = run_python([sys.executable, full], os.path.dirname(full), timeout, limit)
        if code == 0:
            shown = out.strip().splitlines()[-3:] if out.strip() else []
            return f"Ran {path} successfully" + (": " + " | ".join(shown) if shown else " (no output)")
        return f"{path} failed: {explain_python_error(err)}"

    def run_tests(self, folder, timeout, limit):
        import importlib.util
        full = expand(folder)
        if importlib.util.find_spec("pytest") is not None:
            args = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        else:
            args = [sys.executable, "-m", "unittest", "discover", "-q"]
        code, out, err = run_python(args, full, timeout, limit)
        text = (out + "\n" + err).strip().splitlines()
        summary = next((l for l in reversed(text) if re.search(r"passed|failed|error|OK|Ran \d+", l)), "no summary")
        return ("Tests passed: " if code == 0 else "Tests failed: ") + summary.strip("= ")

    def _uri_handler_exists(self, scheme):
        if self.system != "Windows":
            return True
        try:
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme))
            return True
        except OSError:
            return False

    def _paste_text(self, text):
        previous = None
        try:
            previous = self.pyperclip.paste()
        except Exception:
            pass
        self.pyperclip.copy(text)
        self.pyautogui.hotkey(self.mod, "v")
        time.sleep(0.3)
        if previous is not None:
            try:
                self.pyperclip.copy(previous)
            except Exception:
                pass

    def play_youtube(self, query):
        video = first_youtube_video(query)
        if video:
            webbrowser.open(f"https://www.youtube.com/watch?v={video}")
            return f"Playing the top YouTube result for '{query}'"
        webbrowser.open(search_url(query, "youtube"))
        return f"Couldn't pick a video automatically, so I opened YouTube results for '{query}'"

    def _whatsapp_by_phone(self, contact, message, phone):
        from urllib.parse import quote
        uri = f"whatsapp://send?phone={phone}" + (f"&text={quote(message)}" if message else "")
        if self.system == "Windows":
            os.startfile(uri)
        elif self.system == "Darwin":
            subprocess.Popen(["open", uri])
        else:
            subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        spec = app_spec("whatsapp", self.system)
        if not self._wait_for_window(spec, timeout=15):
            raise BackendError("WhatsApp did not open within 15 seconds")
        time.sleep(2.5)
        if not message:
            return f"Opened your WhatsApp chat with {contact}"
        try:
            self.focus_app("whatsapp")
        except BackendError:
            pass
        self.pyautogui.press("enter")
        return f"Sent “{message}” to {contact} on WhatsApp"

    def whatsapp_chat(self, contact, message, phone=None):
        if phone:
            return self._whatsapp_by_phone(contact, message, phone)
        spec = app_spec("whatsapp", self.system)
        if self.system == "Windows" and not self._uri_handler_exists("whatsapp"):
            raise BackendError("the WhatsApp desktop app is not installed. Install it from the Microsoft Store "
                               "(WhatsApp Web can't be controlled reliably)")
        if self.system == "Windows":
            subprocess.Popen('start "" whatsapp:', shell=True)
        elif self.system == "Darwin":
            subprocess.Popen(["open", "-a", "WhatsApp"])
        else:
            subprocess.Popen(shlex.split(spec.launch), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self._wait_for_window(spec, timeout=15):
            raise BackendError("WhatsApp did not open within 15 seconds")
        try:
            self.focus_app("whatsapp")
        except BackendError:
            pass
        time.sleep(1.5)
        self.pyautogui.hotkey(self.mod, "n")
        time.sleep(1.2)
        self._paste_text(contact)
        time.sleep(2.0)
        self.pyautogui.press("enter")
        time.sleep(1.5)
        if not message:
            return (f"Opened WhatsApp search for {contact} and picked the top match. For an exact chat every time, "
                    f"say: save {contact}'s number as <number>")
        self._paste_text(message)
        time.sleep(0.4)
        self.pyautogui.press("enter")
        return f"Sent “{message}” to {contact} on WhatsApp (top search match)"

    def window(self, action):
        self._target()
        if self.system == "Darwin":
            if action == "minimize":
                self.pyautogui.hotkey("command", "m")
            else:
                self.pyautogui.hotkey("ctrl", "command", "f")
        else:
            self.pyautogui.hotkey("win", "down" if action == "minimize" else "up")
        return f"{action.capitalize()}d the window"

    def lock(self):
        if self.system == "Windows":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif self.system == "Darwin":
            self._run(["pmset", "displaysleepnow"])
        else:
            self._run(["loginctl", "lock-session"])
        return "Locked the computer"

    def screenshot(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        image = self.ImageGrab.grab()
        image.save(path)
        copied = self._image_to_clipboard(image, path)
        note = " and copied it to the clipboard" if copied else " (could not copy the image to the clipboard)"
        return f"Saved screenshot to {path}{note}"

    def _image_to_clipboard(self, image, path):
        try:
            if self.system == "Windows":
                import win32clipboard
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, "BMP")
                data = buffer.getvalue()[14:]
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                finally:
                    win32clipboard.CloseClipboard()
                return True
            if self.system == "Darwin":
                script = f'set the clipboard to (read (POSIX file "{os.path.abspath(path)}") as «class PNGf»)'
                return self._osascript(script).returncode == 0
            if shutil.which("xclip"):
                with open(path, "rb") as fh:
                    return subprocess.run(["xclip", "-selection", "clipboard", "-t", "image/png", "-i"],
                                          stdin=fh).returncode == 0
        except Exception:
            return False
        return False

    def type_text(self, text):
        self._target()
        if len(text) > 25 or not text.isascii() or "\n" in text:
            self._paste_text(text)
        else:
            self.pyautogui.write(text, interval=0.01)
        shown = text if len(text) <= 60 else text[:57] + "..."
        return f"Typed: '{shown}'"

    def press(self, keys):
        self._target()
        if len(keys) == 1:
            self.pyautogui.press(keys[0])
        else:
            self.pyautogui.hotkey(*keys)
        return f"Pressed {'+'.join(keys)}"

    def copy(self):
        self._target()
        self.pyautogui.hotkey(self.mod, "c")
        time.sleep(0.2)
        return "Copied current selection"

    def paste(self, target):
        self._target()
        self.pyautogui.hotkey(self.mod, "v")
        time.sleep(0.3)
        return f"Pasted into {target or 'active window'}"

    def select_all(self):
        self._target()
        self.pyautogui.hotkey(self.mod, "a")
        return "Selected everything"

    def save(self, filename):
        self._target()
        self.pyautogui.hotkey(self.mod, "s")
        if filename:
            time.sleep(1.2)
            self.pyautogui.write(filename, interval=0.02)
            self.pyautogui.press("enter")
            return f"Saved as {filename}"
        return "Saved current file"

    def file_exists(self, path):
        return os.path.exists(expand(path))

    def create_file(self, path):
        full = expand(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "a").close()
        return f"Created {path}"

    def delete_file(self, path):
        full = expand(path)
        if not os.path.isfile(full):
            raise BackendError(f"cannot delete '{path}': no such file")
        os.remove(full)
        return f"Deleted {path}"

    def wait(self, seconds):
        time.sleep(seconds)
        return f"Waited {seconds} second(s)"

    def scroll(self, direction, amount):
        hwnd = self._target()
        if hwnd is not None:
            x, y = self.focus.centre(hwnd)
            self.pyautogui.moveTo(x, y, duration=0.1)
        clicks = amount * (120 if self.system == "Windows" else 1)
        self.pyautogui.scroll(clicks if direction == "up" else -clicks)
        return f"Scrolled {direction}"

    def volume(self, action):
        if self.system == "Windows":
            if action in ("mute", "unmute"):
                self.pyautogui.press("volumemute")
            else:
                self.pyautogui.press("volumeup" if action == "up" else "volumedown", presses=5)
        elif self.system == "Darwin":
            scripts = {
                "up": "set volume output volume ((output volume of (get volume settings)) + 10)",
                "down": "set volume output volume ((output volume of (get volume settings)) - 10)",
                "mute": "set volume output muted true",
                "unmute": "set volume output muted false",
            }
            self._osascript(scripts[action])
        else:
            commands = {
                "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
                "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
                "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            }
            if not shutil.which("pactl"):
                raise BackendError("volume control on Linux needs pactl (PulseAudio/PipeWire)")
            self._run(commands[action])
        return f"Volume {action}"

    def click_text(self, label):
        try:
            import pytesseract
        except ImportError as e:
            raise BackendError("clicking by name needs OCR: pip install pytesseract and install Tesseract") from e
        image = self.ImageGrab.grab()
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractNotFoundError as e:
            raise BackendError("Tesseract OCR is not installed; see README for setup") from e
        box = find_text_box(data, label)
        if box is None:
            raise BackendError(f"could not find '{label}' on the screen")
        screen_w, screen_h = self.pyautogui.size()
        scale_x, scale_y = screen_w / image.width, screen_h / image.height
        x, y = box
        self.pyautogui.click(int(x * scale_x), int(y * scale_y))
        time.sleep(0.4)
        return f"Clicked '{label}'"


def _clean(word):
    return "".join(ch for ch in word.lower() if ch.isalnum())


def find_text_box(data, label):
    wanted = [_clean(w) for w in label.split() if _clean(w)]
    if not wanted:
        return None
    words = [_clean(w) for w in data["text"]]
    best = None
    for i in range(len(words) - len(wanted) + 1):
        if words[i:i + len(wanted)] != wanted:
            continue
        span = range(i, i + len(wanted))
        confs = [float(data["conf"][k]) for k in span]
        score = sum(confs) / len(confs)
        left = min(data["left"][k] for k in span)
        top = min(data["top"][k] for k in span)
        right = max(data["left"][k] + data["width"][k] for k in span)
        bottom = max(data["top"][k] + data["height"][k] for k in span)
        centre = ((left + right) / 2, (top + bottom) / 2)
        if best is None or score > best[0]:
            best = (score, centre)
    return best[1] if best else None
