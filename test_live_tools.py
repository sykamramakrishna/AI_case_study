import os
import tempfile
import threading

from compiler_agent.assistant import Assistant
from compiler_agent.backends import explain_python_error
from compiler_agent.executor import ExecutionCancelled
from compiler_agent.policy import Policy


def live(tmp, **kw):
    policy = Policy(allowed_roots=[tmp], script_timeout=kw.pop("timeout", 10))
    return Assistant(dry_run=False, policy=policy, **kw)


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
def test_write_text_into_file_and_verify(tmp):
    a = live(tmp)
    a.handle("write hello world into notes.txt")
    a.handle("add second line into notes.txt")
    assert open(os.path.join(tmp, "notes.txt")).read() == "hello world\nsecond line\n"


@in_tmp
def test_create_folder_real(tmp):
    a = live(tmp)
    out = a.handle("create a new folder called lab reports")
    assert out.kind == "ir" and os.path.isdir(os.path.join(tmp, "lab reports"))


@in_tmp
def test_run_script_success(tmp):
    open("hello.py", "w").write("print('hi from script')\n")
    out = live(tmp).handle("run hello.py")
    assert "successfully" in out.message and "hi from script" in out.message


@in_tmp
def test_run_script_error_is_explained(tmp):
    open("bad.py", "w").write("x = 1\nprint(y)\n")
    out = live(tmp).handle("run bad.py")
    assert "NameError" in out.message and "line 2" in out.message and "misspelled" in out.message


@in_tmp
def test_run_script_timeout(tmp):
    open("loop.py", "w").write("while True:\n    pass\n")
    out = live(tmp, timeout=2).handle("run loop.py")
    assert out.kind == "failed" and "stopped after 2 seconds" in out.message


@in_tmp
def test_run_tests(tmp):
    open("test_math.py", "w").write("def test_add():\n    assert 1 + 1 == 2\n\ndef test_bad():\n    assert 2 * 2 == 5\n")
    out = live(tmp).handle("run the tests")
    assert out.message.startswith("Tests failed") and "1 failed" in out.message and "1 passed" in out.message


@in_tmp
def test_outside_allowed_folder_refused(tmp):
    out = live(tmp).handle("delete /etc/hosts")
    assert out.kind == "reject" and "outside the folders" in out.message


@in_tmp
def test_delete_missing_file_reports_failure(tmp):
    out = live(tmp).handle("delete ghost.txt")
    assert out.kind == "failed" and "no such file" in out.message


@in_tmp
def test_confirmation_declined_skips_script(tmp):
    open("hello.py", "w").write("open('ran.txt','w').write('x')\n")
    out = live(tmp, confirm=lambda d: False).handle("run hello.py")
    assert out.message.startswith("Skipped") and not os.path.exists("ran.txt")


@in_tmp
def test_cancel_stops_between_steps(tmp):
    a = live(tmp)
    ir = a.interpret("wait 1 second and create a.txt and wait 1 second and create b.txt").ir
    threading.Timer(0.5, a.agent.executor.cancel).start()
    try:
        a.agent.run_ir(ir)
        assert False, "expected cancellation"
    except ExecutionCancelled as e:
        assert len(e.done) == 1
    assert not os.path.exists("a.txt")


@in_tmp
def test_partial_failure_reports_done_steps(tmp):
    out = live(tmp).handle("create one.txt and delete ghost.txt and create two.txt")
    assert out.kind == "failed" and os.path.exists("one.txt") and not os.path.exists("two.txt")


def test_explain_python_error_syntax():
    msg = explain_python_error('  File "x.py", line 3\n    def f(\n         ^\nSyntaxError: \'(\' was never closed')
    assert "line 3 of x.py" in msg and "not valid Python" in msg


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
