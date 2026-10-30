import os
import tempfile

from compiler_agent.assistant import Assistant, dictation_text
from compiler_agent.backends import DryRunBackend, parse_first_video
from compiler_agent.memory_store import Memory
from compiler_agent.ui_api import CompilerApi
from compiler_agent.wake import WakeGate


def ops(text, **kw):
    o = Assistant(dry_run=True, **kw).interpret(text)
    return o, [(x["op"], x["target"]) for x in (o.ir or [])]


def test_wake_word_gate():
    g = WakeGate()
    assert g.check("open notepad") == ("ignored", "")
    assert g.check("hey compiler") == ("woke", "")
    assert g.check("open notepad") == ("command", "open notepad")
    assert g.check("stop") == ("sleep", "")
    assert g.check("open chrome") == ("ignored", "")
    assert g.check("Hey Compiler, play kesariya") == ("command", "play kesariya")
    assert g.check("hey computer open chrome") == ("command", "open chrome")


def test_wake_gate_always_mode_and_force():
    assert WakeGate(mode="always").check("open notepad") == ("command", "open notepad")
    assert WakeGate().check("yes", force=True) == ("command", "yes")


def test_wake_gate_holds_awake_while_dictating():
    g = WakeGate(awake_seconds=0)
    g.hold = True
    assert g.check("this is my sentence") == ("command", "this is my sentence")


def test_play_youtube_variants():
    for said, query in (("play kesariya song", "kesariya song"), ("play arijit singh songs on youtube", "arijit singh songs"),
                        ("open youtube and play lofi music", "lofi music"), ("put on some lofi beats", "some lofi beats")):
        o = Assistant(dry_run=True).interpret(said)
        assert o.ir[0]["op"] == "PLAY" and o.ir[0]["args"]["query"] == query, said


def test_media_keys():
    for said, key in (("pause the song", "playpause"), ("resume the video", "playpause"), ("next song", "nexttrack"),
                      ("skip this song", "nexttrack"), ("previous song", "prevtrack")):
        o = Assistant(dry_run=True).interpret(said)
        assert o.ir[0]["args"]["keys"] == [key], said


def test_parse_first_video():
    html = 'xx"videoRenderer":{"videoId":"dQw4w9WgXcQ","thumbnail"yy /watch?v=AAAAAAAAAAA'
    assert parse_first_video(html) == "dQw4w9WgXcQ"
    assert parse_first_video("/watch?v=BBBBBBBBBBB") == "BBBBBBBBBBB"
    assert parse_first_video("nothing") is None


def test_open_reuses_running_app_unless_new():
    b = DryRunBackend()
    assert b.open_app("notepad") == "Would open application: notepad"
    assert b.open_app("notepad") == "Would switch to notepad (already open)"
    assert b.open_app("notepad", new=True) == "Would open application: notepad"
    o, _ = ops("open a new notepad")
    assert o.ir[0]["args"]["new"] is True


def test_contacts_make_whatsapp_exact():
    a = Assistant(dry_run=True, memory=Memory(":memory:"))
    assert "Saved rahul" in a.handle("save rahul's number as 98765 43210").message.replace("Rahul", "rahul")
    out = a.handle("open whatsapp chat with Rahul")
    assert out.ir[0]["args"]["phone"] == "919876543210" and "directly" in out.message
    assert a.handle("Asish's number is +91 91234 56789").kind == "memory"
    assert a.memory.contact("asish") == "919123456789"
    assert "Removed" in a.handle("forget rahul's number").message
    assert a.handle("save rahul's number as 123").kind in ("reject", "ir", "clarify")


def test_dictation_mode_types_everything_until_stop():
    a = Assistant(dry_run=True)
    start = a.handle("start dictation in notepad")
    assert start.kind == "ir" and a.dictating["app"] == "notepad"
    t1 = a.handle("hello my name is pavanji comma I study at VIT full stop new line open chrome")
    typed = t1.ir[-1]["args"]["text"]
    assert typed == "Hello my name is pavanji, I study at VIT.\nOpen chrome"
    assert t1.message == ""
    t2 = a.handle("delete everything")
    assert t2.ir[-1]["op"] == "TYPE_TEXT" and t2.ir[-1]["args"]["text"] == " delete everything"
    assert a.handle("stop dictation").message == "Dictation stopped."
    assert a.handle("open chrome").ir[0]["op"] == "OPEN_APP"


def test_dictation_spoken_punctuation():
    assert dictation_text("hi comma how are you question mark", True) == "Hi, how are you?"
    assert dictation_text("next point new paragraph done", False) == " next point\n\nDone"


class Writer:
    def compose(self, request, max_words=220):
        self.request = request
        return "Compilers translate source code into machine code. They work in phases."


def test_ai_writing_into_notepad():
    w = Writer()
    out = Assistant(dry_run=True, llm=w).handle("write a paragraph about compilers in notepad")
    assert w.request == "Write a paragraph about compilers."
    assert [o["op"] for o in out.ir] == ["OPEN_APP", "WAIT", "TYPE_TEXT"]
    assert out.ir[-1]["args"]["text"].startswith("Compilers translate")


def test_ai_writing_needs_model():
    out = Assistant(dry_run=True).handle("write an essay on climate change")
    assert out.kind == "reject" and "AI model" in out.message


def test_bridge_wake_flow():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            api = CompilerApi(dry_run=True, speak=False)

            class T:
                def __init__(self, text):
                    self.text = self.raw = text
                    self.alternatives, self.engine, self.confidence, self.uncertain, self.latency_ms = [], "google", 0.9, False, 500

            heard = [T("open notepad"), T("hey compiler"), T("open notepad"), T("stop")]

            class FakeSpeech:
                notes = []
                engine = "google"

                def listen(self, **kw):
                    return heard.pop(0)

            api.speech = FakeSpeech()
            assert api.listen()["ignored"]
            assert api.listen()["woke"]
            assert api.listen()["text"] == "open notepad"
            assert api.listen()["slept"]
            assert api.status()["awake"] is False
        finally:
            os.chdir(old)


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
