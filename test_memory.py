from compiler_agent.assistant import Assistant
from compiler_agent.memory_store import Memory


def make():
    return Assistant(dry_run=True, memory=Memory(":memory:"))


def test_alias_used_in_commands():
    a = make()
    assert a.handle("remember that my project folder is D:\\cn").kind == "memory"
    out = a.handle("open my project folder")
    assert out.ir[0]["op"] == "OPEN_FILE" and out.ir[0]["target"] == "D:\\cn"


def test_alias_for_website():
    a = make()
    a.handle("remember that college portal means vtop")
    assert a.handle("open college portal").ir[0]["args"]["url"] == "https://vtop.vit.ac.in"


def test_alias_not_applied_inside_dictation():
    a = make()
    a.handle("remember that college portal is vtop")
    assert a.handle("type I love my college portal").ir[0]["args"]["text"] == "I love my college portal"


def test_recall_lists_only_real_rows():
    a = make()
    assert "0 past commands" in a.handle("what do you remember").message
    a.handle("remember that report is final_report.docx")
    a.handle("open notepad")
    msg = a.handle("what do you remember").message
    assert "'report' means final_report.docx" in msg and "1 past commands" in msg


def test_forget_one_and_all():
    a = make()
    a.handle("remember that portal is vtop")
    assert "Forgot" in a.handle("forget portal").message
    assert "nothing saved" in a.handle("forget portal").message
    a.handle("remember that x is notepad")
    assert a.handle("forget everything").kind == "clarify"
    a.handle("yes")
    assert a.memory.aliases() == {}


def test_sensitive_never_stored():
    a = make()
    assert a.handle("remember that my password is hunter2").kind == "reject"
    a.handle("type my otp is 482913")
    assert a.memory.history() == []
    assert a.handle("remember that card is 4111 1111 1111 1111").kind == "reject"


def test_history_can_be_turned_off_and_cleared():
    a = make()
    a.handle("open notepad")
    a.handle("stop saving my history")
    a.handle("open chrome")
    assert len(a.memory.history()) == 1
    a.handle("clear my history")
    assert a.memory.history() == []


def test_delete_everything_is_not_a_memory_command():
    a = make()
    assert a.handle("delete everything").kind == "reject"


def test_no_memory_session():
    assert Assistant().handle("what do you remember").message == "Memory is turned off in this session."


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
