import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from compiler_agent.memory_store import Memory
from compiler_agent.policy import Policy
from compiler_agent.ui_api import CompilerApi

SCRIPT = [
    "open notepad and type hello from compiler",
    "take a screenshot and paste it into word",
    "um tape hello world",
    "open chrome no wait open firefox",
    "if notes.txt exists then open notes.txt otherwise create notes.txt",
    "press tab 3 times and wait 2 seconds and wait 1 second",
    "what is 25 into 4",
    "delete",
    "notes.txt",
    "close all google tabs",
    "what do you remember",
    "shut down the computer",
    "paste into word",
]


def record():
    os.chdir(tempfile.mkdtemp())
    api = CompilerApi(dry_run=True, memory=Memory(":memory:"), speak=False, policy=Policy(allowed_roots=[os.getcwd()]))
    samples = []
    for said in SCRIPT:
        report = api.process(said)
        sample = {"said": said, "report": report}
        if report["kind"] == "ir":
            sample["exec"] = api.execute(True)
        samples.append(sample)
    return samples


def main(out=None):
    page = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    samples = json.dumps(record(), separators=(",", ":")).replace("</", "<\\/")
    page = page.replace('<script type="application/json" id="samples">[]</script>',
                        f'<script type="application/json" id="samples">{samples}</script>')
    head = re.search(r"<head>(.*)</head>", page, re.S).group(1)
    head = re.sub(r'<meta charset="utf-8">\s*|<meta name="viewport"[^>]*>\s*', "", head)
    body = re.search(r"<body>(.*)</body>", page, re.S).group(1)
    fragment = head.replace("<title>", '<meta name="claude:viewport-fit-sides" content="cover">\n<title>', 1) + body
    out = out or os.path.join(HERE, "preview.html")
    open(out, "w", encoding="utf-8").write(fragment)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
