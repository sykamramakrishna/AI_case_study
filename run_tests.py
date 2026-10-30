import subprocess
import sys

SUITES = ["test_pipeline.py", "test_assistant.py", "test_speech.py", "test_memory.py", "test_llm.py",
          "test_live_tools.py", "test_ui_api.py", "test_whatsapp.py", "test_voice_features.py", "test_smooth.py"]


def main():
    failed = 0
    for suite in SUITES:
        out = subprocess.run([sys.executable, suite], capture_output=True, text=True)
        last = [l for l in out.stdout.strip().splitlines() if l.strip()][-1:] or ["no output"]
        print(f"{suite:<22} {last[0]}")
        for line in out.stdout.splitlines():
            if line.startswith("FAIL"):
                print("   " + line)
        failed += " 0 failed" not in last[0]
    subprocess.run([sys.executable, "eval/evaluate.py", "--set", "all"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
