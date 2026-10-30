import json
import os
import tempfile

from app import JsBridge
from compiler_agent.llm import Proposal
from compiler_agent.memory_store import Memory
from compiler_agent.policy import Policy
from compiler_agent.ui_api import CompilerApi


def bridge(**kw):
    kw.setdefault("speak", False)
    return JsBridge(CompilerApi(**kw))


def test_reports_are_json_serializable_for_the_page():
    b = bridge(memory=Memory(":memory:"))
    for t in ("um tape hello world", "delete", "notes.txt", "shut down the computer", "paste into word",
              "remember that portal is vtop", "what is 25 into 4"):
        r = b.process(t)
        json.dumps(r)
        if r["kind"] == "ir":
            json.dumps(b.execute(True))


def test_full_stage_report_for_commands():
    r = bridge().process("um tape hello world")
    assert r["kind"] == "ir" and r["understood"] == "type hello world"
    assert set(r["stages"]) == {"lexer", "parser", "semantic", "optimizer", "ir"}
    assert ["tape", "type"] in r["corrections"]


def test_error_stage_reported():
    b = bridge()
    assert b.process("paste into word")["error"]["stage"] == "semantic"
    assert b.process("blorp fnord")["error"]["stage"] == "parser"


def test_confirm_flow_decline_skips():
    b = bridge()
    r = b.process("close all google tabs")
    assert r["confirms"] and "close chrome" in r["confirms"][0]
    e = b.execute(False)
    assert e["results"][0].startswith("Skipped")


def test_clarify_then_answer_keeps_pending():
    b = bridge()
    r = b.process("delete")
    assert r["kind"] == "clarify" and r["pending"] == "Which file should I delete?"
    assert b.status()["pending"] == "Which file should I delete?"
    r2 = b.process("zz_missing.txt")
    assert r2["understood"] == "delete zz_missing.txt"


def test_execute_without_pending():
    assert bridge().execute(True)["kind"] == "reject"


def test_mode_switch_runs_for_real():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            b = bridge(policy=Policy(allowed_roots=[tmp]))
            assert b.status()["mode"] == "dry"
            b.process("create folder alpha")
            b.execute(True)
            assert not os.path.isdir("alpha")
            assert b.set_mode("live")["mode"] == "live"
            b.process("create folder alpha")
            assert "Created folder alpha" in b.execute(True)["message"]
            assert os.path.isdir("alpha")
        finally:
            os.chdir(old)


class CodeLLM:
    model = "qwen3:8b"

    def available(self):
        return True

    def translate(self, text, context=None):
        return Proposal("code", "write hi.py", filename="hi.py", code="print('hi')\n")


def test_code_review_flow_writes_once_without_second_confirm():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            b = bridge(dry_run=False, llm=CodeLLM(), policy=Policy(allowed_roots=[tmp]))
            r = b.process("make a program that says hi")
            assert r["code"]["filename"] == "hi.py" and "print('hi')" in r["code"]["preview"]
            assert r["stages"] == {}
            saved = b.process("yes")
            assert saved["via"] == "llm-code" and saved["confirms"] == []
            assert "Wrote" in b.execute(True)["message"] and open("hi.py").read() == "print('hi')\n"
        finally:
            os.chdir(old)


def test_status_shape():
    s = bridge(llm=CodeLLM(), memory=Memory(":memory:")).status()
    assert s["llm"] == {"model": "qwen3:8b", "ready": True} and s["memory"] is True
    assert s["engine"] in ("whisper", "google")


def test_bridge_exposes_only_public_methods():
    names = {n for n in dir(JsBridge) if not n.startswith("_")}
    assert names == {"status", "process", "execute", "listen", "set_mode", "set_speak", "stop", "memory_summary", "greet", "set_wake_mode"}


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {len(tests) - passed} failed")


def test_listen_survives_network_hiccup_and_is_single_flight():
    import threading as th
    from compiler_agent.speech import SpeechTransient
    from compiler_agent.ui_api import CompilerApi
    api = CompilerApi(dry_run=True, speak=False)
    gate = th.Event()

    class Flaky:
        notes = []
        engine = "google"
        calls = 0

        def listen(self, **kw):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise SpeechTransient("slow internet")
            gate.wait(2)
            return None

    api.speech = Flaky()
    r = api.listen()
    assert r["transient"] and "error" in r
    t = th.Thread(target=api.listen)
    t.start()
    import time
    time.sleep(0.1)
    assert api.listen().get("busy")
    gate.set()
    t.join()
    assert api.status()["speech_error"] is None
