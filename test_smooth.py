import threading
import time

from compiler_agent.speech import SpeechFrontend, Transcript, spoken_form
from compiler_agent.wake import WakeGate


class FakeSource:
    CHUNK = 1024

    class stream:
        @staticmethod
        def read(n):
            time.sleep(0.01)
            return b""


class FakeSpeaker:
    def __init__(self):
        self.speaking = False
        self.last_active = 0.0


def streaming_frontend(phrases, recognise_delay=0.0, speaker=None, gap=0.05):
    sf = SpeechFrontend(engine="google")
    sf._open = lambda: FakeSource()
    pending = list(phrases)
    lock = threading.Lock()

    def fake_listen(source, timeout=None, phrase_time_limit=None):
        time.sleep(gap)
        with lock:
            if not pending:
                time.sleep(timeout or 0.1)
                raise sf.sr.WaitTimeoutError()
            item = pending.pop(0)
        if callable(item):
            item = item()
        return item

    sf.recognizer.listen = fake_listen

    def fake_transcribe(audio):
        time.sleep(recognise_delay)
        return Transcript(text=audio, raw=audio, engine="fake")

    sf.transcribe = fake_transcribe
    sf.start_stream(speaker)
    return sf


def test_stream_returns_phrases_in_order():
    sf = streaming_frontend(["open notepad", "type hello", "save"])
    got = [sf.listen(timeout=3).text for _ in range(3)]
    sf.stop_stream()
    assert got == ["open notepad", "type hello", "save"], got


def test_stream_recognises_in_parallel():
    sf = streaming_frontend(["one", "two"], recognise_delay=0.6, gap=0.02)
    start = time.time()
    got = [sf.listen(timeout=3).text for _ in range(2)]
    took = time.time() - start
    sf.stop_stream()
    assert got == ["one", "two"] and took < 1.05, (got, took)


def test_stream_keeps_listening_while_previous_command_runs():
    sf = streaming_frontend(["open chrome", "play kesariya"])
    first = sf.listen(timeout=3)
    time.sleep(0.5)
    start = time.time()
    second = sf.listen(timeout=3)
    took = time.time() - start
    sf.stop_stream()
    assert first.text == "open chrome" and second.text == "play kesariya" and took < 0.1, took


def test_stream_drops_its_own_voice():
    speaker = FakeSpeaker()

    def spoken_while_capturing():
        speaker.last_active = time.time() + 0.01
        return "opened notepad"

    sf = streaming_frontend([spoken_while_capturing, "type hello"], speaker=speaker)
    t = sf.listen(timeout=3)
    sf.stop_stream()
    assert t.text == "type hello", t.text


def test_stream_waits_while_speaker_talks():
    speaker = FakeSpeaker()
    speaker.speaking = True
    sf = streaming_frontend(["open notepad"], speaker=speaker)
    assert sf.listen(timeout=0.4) is None
    speaker.speaking = False
    speaker.last_active = time.time() - 5
    t = sf.listen(timeout=3)
    sf.stop_stream()
    assert t is not None and t.text == "open notepad"


def test_idle_listen_returns_quickly():
    sf = streaming_frontend([])
    start = time.time()
    assert sf.listen(timeout=0.5) is None
    took = time.time() - start
    sf.stop_stream()
    assert took < 0.8, took


def test_flush_drops_queued_commands():
    sf = streaming_frontend(["delete notes.txt", "close chrome"], gap=0.01)
    time.sleep(0.4)
    sf.flush()
    assert sf.listen(timeout=0.3) is None
    sf.stop_stream()


def test_recognition_errors_reach_the_caller():
    from compiler_agent.speech import SpeechTransient
    sf = streaming_frontend(["x"])

    def boom(audio):
        raise SpeechTransient("internet slow")

    sf.transcribe = boom
    try:
        sf.listen(timeout=3)
    except SpeechTransient:
        sf.stop_stream()
        return
    sf.stop_stream()
    raise AssertionError("expected SpeechTransient")


def test_compiler_wake_words():
    for said in ["hey compiler", "Hey Compiler.", "hey complier", "hey compilers", "hi compiler", "compiler",
                 "ok compile", "hey computer", "a compiler"]:
        assert WakeGate().check(said) == ("woke", ""), said
    assert WakeGate().check("hey compiler open notepad") == ("command", "open notepad")
    assert WakeGate().check("Compiler, play kesariya song") == ("command", "play kesariya song")
    for said in ["open notepad", "hey vaani", "compile the code", "hey money"]:
        assert WakeGate().check(said) == ("ignored", ""), said


def test_spoken_reply_skips_brackets():
    assert spoken_form("Switched to notepad (it was already open)") == "Switched to notepad"


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
