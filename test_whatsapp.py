from compiler_agent.assistant import Assistant
from compiler_agent.llm import Proposal


def chat_of(text):
    o = Assistant(dry_run=True).interpret(text)
    assert o.kind == "ir", (text, o.kind, o.message)
    ops = [op for op in o.ir if op["op"] == "CHAT"]
    assert ops, (text, o.ir)
    return ops[0]["target"], ops[0]["args"].get("message")


def test_open_chat_phrasings():
    for said in ("open whatsapp chat with Rahul", "open the chat with Rahul on whatsapp",
                 "open Rahul's chat on WhatsApp", "whatsapp Rahul", "chat with Rahul on whatsapp",
                 "can you please open whatsapp chat with Rahul"):
        assert chat_of(said) == ("Rahul", None), said


def test_send_message_phrasings():
    cases = {
        "open WhatsApp chat with Rahul and say I will be late": ("Rahul", "I will be late"),
        "send a message to Ravi Kumar on WhatsApp saying meeting at 5": ("Ravi Kumar", "meeting at 5"),
        "send happy birthday to Priya on whatsapp": ("Priya", "happy birthday"),
        "tell Asish on whatsapp that the project is done": ("Asish", "the project is done"),
        "message Rahul saying call me": ("Rahul", "call me"),
        "whatsapp mom saying I reached hostel": ("mom", "I reached hostel"),
    }
    for said, want in cases.items():
        assert chat_of(said) == want, said


def test_sending_always_needs_confirmation():
    asked = []
    a = Assistant(dry_run=True, confirm=lambda d: asked.append(d) or False)
    out = a.handle("message Rahul saying call me")
    assert asked and "send “call me” to Rahul on WhatsApp" in asked[0]
    assert out.results[0].startswith("Skipped")


def test_opening_chat_needs_no_confirmation():
    asked = []
    out = Assistant(dry_run=True, confirm=lambda d: asked.append(d) or True).handle("open whatsapp chat with Rahul")
    assert not asked and out.kind == "ir"


def test_chat_without_name_asks_who():
    a = Assistant(dry_run=True)
    q = a.handle("chat")
    assert q.kind == "clarify" and "Who" in q.message
    assert a.handle("Rahul").ir[0]["target"] == "Rahul"


def test_dictation_mentioning_whatsapp_is_typed_not_sent():
    o = Assistant(dry_run=True).interpret("type I will message rahul saying hi")
    assert [op["op"] for op in o.ir] == ["TYPE_TEXT"]


def test_questions_are_not_turned_into_chats():
    for q in ("what does a lexer do", "what is a compiler", "that is great"):
        o = Assistant(dry_run=True).interpret(q)
        assert not o.ir or all(op["op"] != "CHAT" for op in o.ir), q


def test_open_whatsapp_app():
    o = Assistant(dry_run=True).interpret("open whatsapp")
    assert o.ir[0]["op"] == "OPEN_APP" and o.ir[0]["args"]["app"] == "whatsapp"


class RepairLLM:
    def __init__(self):
        self.repaired = []

    def translate(self, text, context=None):
        return Proposal("command", "notepad.exe /c echo hi")

    def repair(self, text, bad, error, context=None):
        self.repaired.append((bad, error))
        return Proposal("command", "open notepad and type hi")


def test_ai_repairs_command_after_compiler_error():
    llm = RepairLLM()
    out = Assistant(dry_run=True, llm=llm).handle("could you get the jotter going and put hi in it")
    assert llm.repaired and out.kind == "ir" and [o["op"] for o in out.ir] == ["OPEN_APP", "TYPE_TEXT"]


class BadRepairLLM(RepairLLM):
    def repair(self, text, bad, error, context=None):
        return Proposal("command", "format everything now")


def test_failed_repair_does_nothing():
    out = Assistant(dry_run=True, llm=BadRepairLLM()).handle("could you get the jotter going and put hi in it")
    assert out.kind == "reject" and out.ir is None


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
