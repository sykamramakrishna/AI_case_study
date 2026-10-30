import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_interpreter():
    try:
        from compiler_agent.assistant import Assistant
    except ImportError:
        Assistant = None
    if Assistant is not None:
        def interpret(text):
            outcome = Assistant(dry_run=True, speak=None, llm=None).interpret(text)
            return outcome.kind, outcome.ir
        return interpret, "assistant"
    from compiler_agent.agent import Agent, CompilationError

    def interpret(text):
        try:
            return "ir", Agent(dry_run=True, echo=False).compile(text)
        except CompilationError:
            return "error", None
        except Exception:
            return "crash", None
    return interpret, "baseline compiler"


def canonical(ir):
    return json.dumps(ir, sort_keys=True) if ir is not None else None


def evaluate(path, interpret, show_failures=False):
    items = json.load(open(path))
    per_cat = defaultdict(lambda: [0, 0])
    failures = []
    for item in items:
        kind, ir = interpret(item["say"])
        if item["expect"] == "same":
            want_kind, want_ir = interpret(item["same_as"])
            ok = kind == "ir" and want_kind == "ir" and canonical(ir) == canonical(want_ir)
            if not ok and want_kind != "ir":
                note = "expected command not supported"
            elif not ok:
                note = f"got {kind}"
            else:
                note = ""
        elif item["expect"] == "clarify":
            ok = kind == "clarify"
            note = f"got {kind}"
        else:
            ok = kind in ("reject", "error")
            note = f"got {kind}"
        per_cat[item["category"]][0] += ok
        per_cat[item["category"]][1] += 1
        if not ok:
            failures.append((item["category"], item["say"], item.get("same_as"), note))
    total_ok = sum(v[0] for v in per_cat.values())
    total = sum(v[1] for v in per_cat.values())
    return per_cat, total_ok, total, failures


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--set", default="dev", choices=["dev", "heldout", "blind", "both", "all"])
    p.add_argument("--failures", action="store_true")
    args = p.parse_args()
    interpret, name = make_interpreter()
    sets = {"both": ["dev", "heldout"], "all": ["dev", "heldout", "blind"]}.get(args.set, [args.set])
    for s in sets:
        path = os.path.join(os.path.dirname(__file__), f"utterances_{s}.json")
        per_cat, ok, total, failures = evaluate(path, interpret)
        print(f"\n== {s} set, {name}: {ok}/{total} = {100 * ok / total:.1f}% ==")
        for cat, (a, b) in per_cat.items():
            print(f"  {cat:<16} {a:>3}/{b:<3} {100 * a / b:5.1f}%")
        if args.failures:
            for cat, say, same, note in failures:
                print(f"  FAIL [{cat}] {say!r} -> want {same!r} ({note})")


if __name__ == "__main__":
    main()
