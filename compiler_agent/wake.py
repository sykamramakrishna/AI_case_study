import re
import time

STRONG = r"compiler|compilers|compiler's|complier|compilar|kompiler|computer|jarvis"
SOFT = r"compile|compiled|compiling|campiler|kampiler|compiller|complire|compiles"
WAKE = re.compile(
    rf"^\s*(?:(?:hey|hi|hello|ok|okay|o\.k\.|hay|hai|he|a)\s+(?:{STRONG}|{SOFT})|(?:{STRONG}))\b[\s,.!?:]*", re.I)
SLEEP = re.compile(
    r"^(?:stop|stop listening|go to sleep|sleep|that's all|thats all|that is all|bye|goodbye|good bye|"
    r"thank you|thanks|thank you compiler|ok thanks|okay thanks|you can stop|be quiet|shut up)$", re.I)


class WakeGate:
    def __init__(self, mode="wake", awake_seconds=40):
        self.mode = mode
        self.awake_seconds = awake_seconds
        self.awake_until = 0.0
        self.hold = False

    @property
    def awake(self):
        return self.mode == "always" or self.hold or time.time() < self.awake_until

    def touch(self):
        self.awake_until = time.time() + self.awake_seconds

    def sleep(self):
        self.awake_until = 0.0

    def check(self, raw, force=False):
        text = (raw or "").strip()
        clean = text.strip(" .!?,")
        if self.mode == "always" or force:
            if SLEEP.match(clean) and not force:
                return "sleep", ""
            self.touch()
            m = WAKE.match(text)
            rest = text[m.end():].strip() if m else text
            return ("woke", "") if not rest else ("command", rest)
        m = WAKE.match(text)
        if m:
            rest = text[m.end():].strip(" ,.")
            self.touch()
            return ("woke", "") if not rest else ("command", rest)
        if not self.awake:
            return "ignored", ""
        if SLEEP.match(clean):
            self.sleep()
            return "sleep", ""
        self.touch()
        return "command", text
