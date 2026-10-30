import os
from dataclasses import dataclass, field
from typing import List


def _norm(path):
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def default_roots():
    home = os.path.expanduser("~")
    roots = [os.getcwd()]
    for name in ("Desktop", "Documents", "Downloads"):
        candidate = os.path.join(home, name)
        roots.append(candidate)
    return roots


@dataclass
class Policy:
    allowed_roots: List[str] = field(default_factory=default_roots)
    script_timeout: int = 30
    test_timeout: int = 120
    max_output_chars: int = 2000

    def allowed(self, path):
        full = _norm(path)
        for root in self.allowed_roots:
            r = _norm(root)
            if full == r or full.startswith(r.rstrip(os.sep) + os.sep):
                return True
        return False

    def describe_roots(self):
        return ", ".join(self.allowed_roots)


DEFAULT_POLICY = Policy()
