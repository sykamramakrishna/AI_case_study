from compiler_agent.assistant import Assistant
from compiler_agent.nlu import understand, phonetic


def conv(*turns, **kw):
    a = Assistant(dry_run=True, **kw)
    return a, [a.handle(t) for t in turns]


def test_clarify_then_fill_slot():
    a, (q, r) = conv("delete", "zz_x.txt")
    assert q.kind == "clarify" and "Which file" in q.message
    assert r.kind == "failed" and "no such file" in r.message


def test_clarify_then_fill_slot_create():
    a, (q, r) = conv("create", "zz_new.txt")
    assert q.kind == "clarify" and r.kind == "ir" and r.ir[0]["op"] == "CREATE_FILE"


def test_clarify_then_new_command_replaces_question():
    a, (q, r) = conv("open", "type hello")
    assert q.kind == "clarify" and r.ir[0]["op"] == "TYPE_TEXT"


def test_clarify_then_cancel():
    a, (q, r) = conv("delete", "never mind")
    assert r.kind == "cancelled" and a.pending is None


def test_cross_turn_correction():
    a, (first, fix) = conv("open chrome", "no, I meant firefox")
    assert fix.ir[0]["args"]["app"] == "firefox"


def test_cross_turn_correction_full_command():
    a, (first, fix) = conv("open chrome", "no open notepad")
    assert fix.ir[0]["args"]["app"] == "notepad"


def test_pronoun_refers_to_last_app():
    a, (first, second) = conv("open notepad", "close it")
    assert second.ir[0]["op"] == "CLOSE_APP" and second.ir[0]["args"]["app"] == "notepad"


def test_pronoun_switch_to_it():
    a, (first, second, third) = conv("open word", "open chrome", "switch to it")
    assert third.ir[0]["args"]["app"] == "chrome"


def test_do_it_again():
    a, (first, second) = conv("press tab", "do it again")
    assert second.ir == first.ir and second.source == "repeat"


def test_again_without_history_rejected():
    a, (only,) = conv("again")
    assert only.kind == "reject"


def test_clipboard_survives_turns():
    a, (shot, paste) = conv("take a screenshot", "paste it into word")
    assert paste.kind == "ir"


def test_unknown_app_asks_then_yes():
    a, (q, r) = conv("open crow", "yes")
    assert q.kind == "clarify" and r.ir[0]["args"]["app"] == "chrome"


def test_unknown_app_close_suggests():
    a, (q,) = conv("close crow")
    assert q.kind == "clarify" and "chrome" in q.message


def test_unknown_app_no_cancels():
    a, (q, r) = conv("open crow", "no")
    assert r.kind == "cancelled"


def test_power_commands_refused():
    for t in ("shut down the computer", "restart my laptop", "log off", "turn off the pc"):
        a, (r,) = conv(t)
        assert r.kind == "reject", t


def test_bulk_delete_refused():
    for t in ("delete everything", "delete all files", "remove every file"):
        a, (r,) = conv(t)
        assert r.kind == "reject", t


def test_alternatives_pick_the_one_that_compiles():
    a = Assistant()
    o = a.interpret("open crumb blob", alternatives=["open chrome", "open crown"])
    assert o.kind == "ir" and o.ir[0]["args"]["app"] == "chrome" and o.source == "alternative"


def test_original_transcript_kept():
    a = Assistant()
    o = a.interpret("um tape hello world")
    assert o.understanding.original == "um tape hello world"
    assert o.text == "type hello world"
    assert ("tape", "type") in o.understanding.corrections


def test_dictation_never_rewritten():
    for spoken in ("type I want to open youtube please", "type turn up the volume", "type no wait"):
        u = understand(spoken)
        assert u.text == spoken, u.text


def test_correction_only_when_needed():
    a = Assistant()
    assert a.interpret("type tape recorder").ir[0]["args"]["text"] == "tape recorder"


def test_answers():
    a, (t, c) = conv("what time is it", "what is 12 into 12")
    assert t.message.startswith("It's") and c.message == "12 * 12 = 144"


def test_phonetic_codes():
    assert phonetic("type") == phonetic("tape")
    assert phonetic("paste") == phonetic("pest")
    assert phonetic("save") == phonetic("safe")


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
