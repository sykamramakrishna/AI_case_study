import os
import re
import sqlite3
import time

SENSITIVE = re.compile(
    r"\b(?:password|passcode|passwd|pin|otp|cvv|secret|api key|token)\b|\b(?:\d[ -]?){12,19}\b", re.I)
DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".vaani", "memory.db")
MAX_HISTORY = 200


def is_sensitive(text):
    return bool(SENSITIVE.search(text or ""))


class Memory:
    def __init__(self, path=DEFAULT_PATH):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS aliases (name TEXT PRIMARY KEY, target TEXT NOT NULL, updated REAL);
            CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created REAL);
            CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT, updated REAL);
            CREATE TABLE IF NOT EXISTS contacts (name TEXT PRIMARY KEY, phone TEXT NOT NULL, updated REAL);
            CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, said TEXT, understood TEXT,
                                                outcome TEXT, created REAL);
        """)
        self.db.commit()

    def set_alias(self, name, target):
        name = name.lower().strip()
        if is_sensitive(name) or is_sensitive(target):
            raise ValueError("that looks like private information, so I won't store it")
        self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?, ?)", (name, target.strip(), time.time()))
        self.db.commit()

    def aliases(self):
        return dict(self.db.execute("SELECT name, target FROM aliases ORDER BY length(name) DESC"))

    def add_note(self, text):
        if is_sensitive(text):
            raise ValueError("that looks like private information, so I won't store it")
        self.db.execute("INSERT INTO notes (text, created) VALUES (?, ?)", (text.strip(), time.time()))
        self.db.commit()

    def notes(self):
        return [r[0] for r in self.db.execute("SELECT text FROM notes ORDER BY id")]

    def set_pref(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO prefs VALUES (?, ?, ?)", (key, str(value), time.time()))
        self.db.commit()

    def pref(self, key, default=None):
        row = self.db.execute("SELECT value FROM prefs WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def log(self, said, understood, outcome):
        if self.pref("history", "on") != "on" or is_sensitive(said) or is_sensitive(understood):
            return
        self.db.execute("INSERT INTO history (said, understood, outcome, created) VALUES (?, ?, ?, ?)",
                        (said, understood, outcome, time.time()))
        self.db.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                        (MAX_HISTORY,))
        self.db.commit()

    def history(self, limit=10):
        return list(self.db.execute("SELECT said, understood, outcome FROM history ORDER BY id DESC LIMIT ?", (limit,)))

    def forget(self, what):
        what = what.lower().strip()
        removed = self.db.execute("DELETE FROM aliases WHERE name = ?", (what,)).rowcount
        removed += self.db.execute("DELETE FROM notes WHERE lower(text) LIKE ?", (f"%{what}%",)).rowcount
        self.db.commit()
        return removed

    def forget_all(self):
        for table in ("aliases", "notes", "prefs", "history", "contacts"):
            self.db.execute(f"DELETE FROM {table}")
        self.db.commit()

    def clear_history(self):
        self.db.execute("DELETE FROM history")
        self.db.commit()

    def set_contact(self, name, phone):
        name = name.lower().strip()
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10:
            digits = self.pref("country_code", "91") + digits
        if not 11 <= len(digits) <= 15:
            raise ValueError("that doesn't look like a phone number (say 10 digits, or include the country code)")
        self.db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, ?)", (name, digits, time.time()))
        self.db.commit()
        return digits

    def contact(self, name):
        row = self.db.execute("SELECT phone FROM contacts WHERE name = ?", (name.lower().strip(),)).fetchone()
        return row[0] if row else None

    def contacts(self):
        return dict(self.db.execute("SELECT name, phone FROM contacts ORDER BY name"))

    def forget_contact(self, name):
        n = self.db.execute("DELETE FROM contacts WHERE name = ?", (name.lower().strip(),)).rowcount
        self.db.commit()
        return n

    def summary(self):
        lines = []
        for name, phone in self.contacts().items():
            lines.append(f"WhatsApp contact {name} (number ending {phone[-4:]})")
        for name, target in sorted(self.aliases().items()):
            lines.append(f"'{name}' means {target}")
        for note in self.notes():
            lines.append(f"note: {note}")
        count = self.db.execute("SELECT count(*) FROM history").fetchone()[0]
        state = "on" if self.pref("history", "on") == "on" else "off"
        lines.append(f"{count} past commands saved (history is {state})")
        return lines
