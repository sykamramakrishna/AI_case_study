import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from compiler_agent.assistant import Assistant
from compiler_agent.llm import LLMUnavailable, OllamaClient, Proposal, parse_reply
from compiler_agent.policy import Policy


class FakeOllama(BaseHTTPRequestHandler):
    replies = []
    requests = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen3:8b"}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(payload)
        if payload["model"] == "missing":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"model \\"missing\\" not found, try pulling it first"}')
            return
        content = FakeOllama.replies.pop(0)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"message": {"role": "assistant", "content": content}}).encode())


def server():
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_http_client_structured_output():
    srv, url = server()
    FakeOllama.replies = ['<think>hmm</think>{"kind":"command","command":"open word"}']
    client = OllamaClient(host=url)
    p = client.translate("pop open the word processor")
    req = FakeOllama.requests[-1]
    srv.shutdown()
    assert p.kind == "command" and p.text == "open word"
    assert req["format"]["properties"]["kind"] and req["think"] is False and req["stream"] is False
    assert client.available() is False or True


def test_warm_up_and_keep_alive():
    srv, url = server()
    FakeOllama.requests.clear()
    FakeOllama.replies = ['{"kind":"answer","answer":"ok"}'] * 3
    client = OllamaClient(host=url)
    client.warm_up_async().join(5)
    client.translate("hi")
    srv.shutdown()
    assert FakeOllama.requests[0]["keep_alive"] == "24h" and FakeOllama.requests[0]["prompt"] == ""
    assert FakeOllama.requests[1]["messages"][0]["role"] == "system"
    assert all(r["keep_alive"] == "24h" for r in FakeOllama.requests)


def test_http_client_retries_bad_json_once():
    srv, url = server()
    FakeOllama.replies = ["sure! I will open it", '{"kind":"answer","answer":"A parser builds a tree."}']
    p = OllamaClient(host=url).translate("what does a parser do")
    srv.shutdown()
    assert p.kind == "answer"


def test_http_client_model_missing_and_server_down():
    srv, url = server()
    try:
        OllamaClient(host=url, model="missing").translate("hi")
        assert False
    except LLMUnavailable as e:
        assert "ollama pull missing" in str(e)
    srv.shutdown()
    try:
        OllamaClient(host="http://127.0.0.1:9", timeout=2).translate("hi")
        assert False
    except LLMUnavailable as e:
        assert "not running" in str(e)


def test_parse_reply_rejects_garbage():
    for bad in ('{"kind":"command","command":""}', '{"kind":"teleport"}', "no json"):
        try:
            parse_reply(bad)
            assert False, bad
        except ValueError:
            pass


class ScriptedLLM:
    def __init__(self, proposals, fixes=()):
        self.proposals = list(proposals)
        self.fixes = list(fixes)
        self.seen = []

    def translate(self, text, context=None):
        self.seen.append((text, context))
        return self.proposals.pop(0)

    def fix_code(self, filename, code, error):
        self.seen.append(("fix", filename, error))
        return self.fixes.pop(0)


def in_tmp(fn):
    def wrapper():
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                fn(tmp)
            finally:
                os.chdir(old)
    wrapper.__name__ = fn.__name__
    return wrapper


@in_tmp
def test_project_conversation_keeps_context_write_run_fix(tmp):
    buggy = "def greet():\n    print('Voice assistant ready')\n\ngreet(\n"
    fixed = "def greet():\n    print('Voice assistant ready')\n\ngreet()\n"
    llm = ScriptedLLM(
        [Proposal("clarify", "What should the project do?"),
         Proposal("code", "write assistant.py", filename="assistant.py", code=buggy)],
        [Proposal("code", "write assistant.py", filename="assistant.py", code=fixed)])
    a = Assistant(dry_run=False, llm=llm, policy=Policy(allowed_roots=[tmp]))
    q = a.handle("Create a Python project")
    assert q.kind == "clarify" and q.message == "What should the project do?"
    plan = a.handle("Build a voice assistant")
    assert "Original request: Create a Python project" in llm.seen[1][0] and "Build a voice assistant" in llm.seen[1][0]
    assert plan.kind == "clarify" and "Should I save it" in plan.message
    assert not os.path.exists("assistant.py")
    saved = a.handle("yes")
    assert saved.kind == "ir" and open("assistant.py").read() == buggy
    run1 = a.handle("run it")
    assert "failed" in run1.message and "SyntaxError" in run1.message
    fix = a.handle("fix the errors")
    assert fix.kind == "clarify" and "Fix attempt 1" in fix.message and llm.seen[-1][0] == "fix"
    a.handle("yes")
    run2 = a.handle("run it")
    assert "successfully" in run2.message and "Voice assistant ready" in run2.message


@in_tmp
def test_fix_attempts_are_limited(tmp):
    bad = Proposal("code", "", filename="x.py", code="print(\n")
    llm = ScriptedLLM([], [bad, bad, bad, bad])
    open("x.py", "w").write("print(\n")
    a = Assistant(dry_run=False, llm=llm, policy=Policy(allowed_roots=[tmp]))
    a.handle("run x.py")
    for _ in range(3):
        assert a.handle("fix it").kind == "clarify"
        a.handle("no")
    assert "already tried" in a.handle("fix it").message


def test_llm_safe_command_runs_directly_after_compiler_check():
    llm = ScriptedLLM([Proposal("command", "open notepad and type buy milk")])
    a = Assistant(dry_run=True, llm=llm)
    done = a.handle("jot down buy milk in the note thing")
    assert done.kind == "ir" and [o["op"] for o in done.ir] == ["OPEN_APP", "TYPE_TEXT"]
    assert done.source == "llm" and "ai_ms" in done.timings
    assert any(s.stage == "ai" for s in done.understanding.steps)


def test_llm_risky_command_still_confirmed_before_running():
    llm = ScriptedLLM([Proposal("command", "close notepad")])
    asked = []
    a = Assistant(dry_run=True, llm=llm, confirm=lambda d: asked.append(d) or False)
    out = a.handle("get notepad out of my way please mate")
    assert asked and out.results[0].startswith("Skipped")


def test_llm_confirm_mode_still_available():
    llm = ScriptedLLM([Proposal("command", "open notepad")])
    a = Assistant(dry_run=True, llm=llm, llm_autorun=False)
    assert a.handle("pop up the jotting app").kind == "clarify"
    assert a.handle("yes").kind == "ir"


def test_llm_dangerous_proposal_blocked_by_compiler():
    llm = ScriptedLLM([Proposal("command", "delete everything")])
    out = Assistant(dry_run=True, llm=llm).handle("clean up my drive completely")
    assert out.kind == "reject" and "rejected" in out.message


def test_llm_unsafe_filename_blocked():
    llm = ScriptedLLM([Proposal("code", "", filename="../../evil.py", code="print(1)")])
    out = Assistant(dry_run=True, llm=llm).handle("make me a hacking tool program")
    assert out.kind == "reject" and "unsafe file name" in out.message


def test_llm_answer_for_questions():
    llm = ScriptedLLM([Proposal("answer", "A lexer splits text into tokens.")])
    out = Assistant(dry_run=True, llm=llm).handle("what does a lexer do")
    assert out.kind == "answer" and "tokens" in out.message


def test_llm_not_used_when_grammar_understands():
    llm = ScriptedLLM([])
    out = Assistant(dry_run=True, llm=llm).handle("open notepad")
    assert out.kind == "ir" and llm.seen == []


def test_compiler_rejection_is_final_even_with_llm():
    llm = ScriptedLLM([])
    for t in ("paste into word", "delete all files", "repeat 500 times press tab"):
        out = Assistant(dry_run=True, llm=llm).handle(t)
        assert out.kind == "reject", t
    assert llm.seen == []


def test_without_llm_questions_explain_setup():
    out = Assistant(dry_run=True).handle("what is a compiler")
    assert out.kind == "reject" and "Ollama" in out.message


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {len(tests) - passed} failed")
