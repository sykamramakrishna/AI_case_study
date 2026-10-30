
from compiler_agent.speech import SpeechFrontend, Speaker, Transcript, normalize_transcript, spoken_form


def fake_frontend(engine):
    sf = SpeechFrontend.__new__(SpeechFrontend)
    import speech_recognition as sr
    sf.sr = sr
    sf.engine = engine
    sf.language = "en-IN"
    sf.notes = []
    sf.recognizer = sr.Recognizer()
    sf._whisper = None
    sf._vosk = None
    return sf


def audio(seconds=1.0):
    import speech_recognition as sr
    return sr.AudioData(b"\x00\x01" * int(16000 * seconds), 16000, 2)


class Seg:
    def __init__(self, text, no_speech=0.05, logprob=-0.2):
        self.text, self.no_speech_prob, self.avg_logprob = text, no_speech, logprob


class FakeWhisper:
    def __init__(self, segs):
        self.segs = segs
        self.kwargs = None

    def transcribe(self, samples, **kw):
        self.kwargs = kw
        assert samples.dtype.name == "float32" and abs(samples).max() <= 1.0
        return iter(self.segs), None


def test_whisper_path_uses_prompt_and_vad():
    sf = fake_frontend("whisper")
    sf._whisper = FakeWhisper([Seg(" Open Notepad and type hello."), Seg(" Then save.")])
    t = sf.transcribe(audio())
    assert t.text == "Open Notepad and type hello. Then save" and t.engine == "whisper"
    assert sf._whisper.kwargs["vad_filter"] and "Notepad" in sf._whisper.kwargs["initial_prompt"]
    assert t.raw.endswith("save.") and not t.uncertain


def test_whisper_rejects_silence_and_prompt_echo():
    sf = fake_frontend("whisper")
    sf._whisper = FakeWhisper([Seg(" you", no_speech=0.9)])
    assert sf.transcribe(audio()) is None
    sf._whisper = FakeWhisper([Seg(" Take a screenshot and paste it into Word. Press control S, tab, enter, escape.")])
    assert sf.transcribe(audio()) is None


def test_whisper_low_confidence_flagged():
    sf = fake_frontend("whisper")
    sf._whisper = FakeWhisper([Seg(" open crow", logprob=-1.3)])
    assert sf.transcribe(audio()).uncertain


def test_google_alternatives_and_confidence():
    sf = fake_frontend("google")
    sf.recognizer.recognize_google = lambda a, language, show_all: {
        "alternative": [{"transcript": "open crow", "confidence": 0.41}, {"transcript": "open chrome"},
                        {"transcript": "open crow"}]}
    t = sf.transcribe(audio())
    assert t.text == "open crow" and t.alternatives == ["open chrome"] and t.uncertain


def test_google_empty_result():
    sf = fake_frontend("google")
    sf.recognizer.recognize_google = lambda a, language, show_all: []
    assert sf.transcribe(audio()) is None


def test_google_unknown_value_is_silence_not_crash():
    sf = fake_frontend("google")

    def unknown(a, language, show_all):
        raise sf.sr.UnknownValueError()
    sf.recognizer.recognize_google = unknown
    assert sf.transcribe(audio()) is None


def test_auto_engine_prefers_google_and_falls_back_to_whisper():
    sf = fake_frontend("google")
    sf.local_available = True

    def offline(a, language, show_all):
        raise sf.sr.RequestError("no internet")
    sf.recognizer.recognize_google = offline
    sf._whisper = FakeWhisper([Seg(" open notepad")])
    t = sf.transcribe(audio())
    assert t.text == "open notepad" and sf.engine == "whisper"


def test_fallback_to_google_when_local_engine_fails():
    sf = fake_frontend("whisper")

    def boom():
        from compiler_agent.speech import SpeechUnavailable
        raise SpeechUnavailable("no model")
    sf._load_whisper = boom
    sf.recognizer.recognize_google = lambda a, language, show_all: {"alternative": [{"transcript": "open notepad"}]}
    t = sf.transcribe(audio())
    assert t.text == "open notepad" and sf.engine == "google" and sf.notes


def test_spoken_form_is_short_and_pronounceable():
    assert spoken_form("Would open https://www.youtube.com/results?x=1") == "I would open youtube.com"
    assert "dot T X T" in spoken_form("Created notes.txt")
    assert spoken_form("25 * 4 = 100").startswith("25 times 4")
    assert spoken_form("x " * 200).endswith("The details are on screen.")


def test_speaker_dedupes_and_never_blocks_without_engine():
    s = Speaker(enabled=False)
    s.say("hello", show=False)
    assert not s.speaking


def test_transcript_str():
    assert str(Transcript("open notepad")) == "open notepad"
    assert normalize_transcript(Transcript("Open Chrome.")) == "Open Chrome"


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


def test_google_timeout_is_transient_and_does_not_hang():
    from compiler_agent.speech import SpeechTransient
    sf = fake_frontend("google")
    sf.local_available = False

    def slow(a, language, show_all):
        raise TimeoutError("timed out")
    sf.recognizer.recognize_google = slow
    try:
        sf.transcribe(audio())
        assert False
    except SpeechTransient as e:
        assert "say it again" in str(e)
    assert sf.engine == "google"


def test_google_comes_back_after_whisper_fallback():
    sf = fake_frontend("whisper")
    sf._google_retry_at = 1.0
    sf.recognizer.recognize_google = lambda a, language, show_all: {"alternative": [{"transcript": "open chrome"}]}
    t = sf.transcribe(audio())
    assert t.text == "open chrome" and sf.engine == "google"


def test_energy_guard_resets_runaway_threshold():
    sf = fake_frontend("google")
    sf.base_energy = 300
    sf.recognizer.energy_threshold = 5000
    sf._guard_energy()
    assert sf.recognizer.energy_threshold == 450
