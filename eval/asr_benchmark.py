import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler_agent.assistant import Assistant
from compiler_agent.nlu import levenshtein
from compiler_agent.speech import SpeechFrontend, SpeechUnavailable

PROMPTS = [
    "open notepad and type hello world",
    "take a screenshot and paste it into word",
    "open youtube and search for compiler design lectures",
    "create a folder called cn lab",
    "create notes dot txt",
    "press control s",
    "press tab three times",
    "wait five seconds",
    "what is twenty five times four",
    "what time is it",
    "open microsoft powerpoint",
    "open vs code",
    "switch to chrome",
    "close notepad",
    "scroll down",
    "volume up",
    "search for vit vellore hostel fees",
    "open whatsapp",
    "open github",
    "go to vtop",
    "minimize the window",
    "type my name is pavanji",
    "search youtube for arijit singh songs",
    "open file explorer",
    "calculate fifteen percent of two thousand",
    "open chrome no wait open firefox",
    "create a python file called sorting",
    "if notes dot txt exists then open notes dot txt otherwise create notes dot txt",
    "open word and type the lexical analyzer converts characters into tokens",
    "lock my computer",
]


def words(text):
    return re.sub(r"[^a-z0-9' ]", " ", text.lower().replace(".", " dot ")).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    if not r:
        return 0.0
    return levenshtein(r, h) / len(r)


def ir_of(text):
    outcome = Assistant(dry_run=True).interpret(text)
    return outcome.kind, json.dumps(outcome.ir, sort_keys=True) if outcome.ir else None


def record(folder, engine):
    os.makedirs(folder, exist_ok=True)
    sf = SpeechFrontend(engine=engine)
    print("Calibrating, stay quiet...")
    sf.calibrate()
    manifest = []
    for i, prompt in enumerate(PROMPTS, 1):
        input(f"\n[{i}/{len(PROMPTS)}] Press Enter, then say:\n   {prompt}\n")
        audio = sf.capture(timeout=8, phrase_limit=20)
        if audio is None:
            print("   (nothing captured, skipped)")
            continue
        path = os.path.join(folder, f"{i:02d}.wav")
        with open(path, "wb") as fh:
            fh.write(audio.get_wav_data(convert_rate=16000))
        manifest.append({"file": os.path.basename(path), "reference": prompt})
    json.dump(manifest, open(os.path.join(folder, "manifest.json"), "w"), indent=1)
    print(f"\nSaved {len(manifest)} recordings to {folder}")


def run(folder, engines, vosk_model):
    manifest = json.load(open(os.path.join(folder, "manifest.json")))
    expected = {m["reference"]: ir_of(m["reference"]) for m in manifest}
    report = {}
    for engine in engines:
        try:
            sf = SpeechFrontend(engine=engine, vosk_model=vosk_model)
        except SpeechUnavailable as e:
            print(f"{engine}: unavailable ({e})")
            continue
        rows, total_wer, ok_cmd, latency = [], 0.0, 0, []
        for m in manifest:
            t0 = time.perf_counter()
            try:
                t = sf.transcribe_file(os.path.join(folder, m["file"]))
            except SpeechUnavailable as e:
                print(f"{engine}: {e}")
                break
            latency.append((time.perf_counter() - t0) * 1000)
            hyp = t.text if t else ""
            e = wer(m["reference"], hyp)
            alts = t.alternatives if t else []
            got = Assistant(dry_run=True).interpret(hyp, alternatives=alts) if hyp else None
            got_key = (got.kind, json.dumps(got.ir, sort_keys=True) if got and got.ir else None) if got else ("none", None)
            good = got_key == expected[m["reference"]]
            total_wer += e
            ok_cmd += good
            rows.append({"reference": m["reference"], "heard": hyp, "wer": round(e, 3), "command_ok": good,
                         "understood_as": got.text if got else ""})
        if not rows:
            continue
        n = len(rows)
        report[engine] = {
            "mean_wer": round(total_wer / n, 3),
            "command_accuracy": round(ok_cmd / n, 3),
            "mean_latency_ms": round(sum(latency) / len(latency)),
            "notes": sf.notes,
            "rows": rows,
        }
        print(f"\n== {engine}: WER {100 * total_wer / n:.1f}%  command accuracy {100 * ok_cmd / n:.1f}%  "
              f"latency {sum(latency) / len(latency):.0f} ms ==")
        for r in rows:
            if not r["command_ok"]:
                print(f"   x said {r['reference']!r}\n     heard {r['heard']!r} -> {r['understood_as']!r}")
    out = os.path.join(folder, "results.json")
    json.dump(report, open(out, "w"), indent=1)
    print(f"\nFull results saved to {out}")


def main():
    p = argparse.ArgumentParser(description="Measure speech recognition accuracy on your own voice and microphone.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--folder", default=os.path.join(ROOT, "eval", "recordings", "quiet"))
    r.add_argument("--engine", default="google")
    b = sub.add_parser("run")
    b.add_argument("--folder", default=os.path.join(ROOT, "eval", "recordings", "quiet"))
    b.add_argument("--engines", default="google,whisper")
    b.add_argument("--vosk-model")
    args = p.parse_args()
    if args.cmd == "record":
        record(args.folder, args.engine)
    else:
        run(args.folder, [e.strip() for e in args.engines.split(",") if e.strip()], args.vosk_model)


if __name__ == "__main__":
    main()
