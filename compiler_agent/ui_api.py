import threading
import time

from .agent import Agent
from .assistant import CONTROL, Assistant
from .executor import Executor, describe
from .lexer import Lexer, LexerError
from .parser import Parser, ParserError
from .serialize import ast_to_json, tokens_to_json
from .speech import Speaker, SpeechFrontend, SpeechTransient, SpeechUnavailable, normalize_transcript
from .wake import WakeGate


def stage_view(text, policy, clipboard=None):
    view = {"stages": {}, "error": None}
    try:
        tokens = Lexer(text).tokenize()
    except LexerError as e:
        view["error"] = {"stage": "lexer", "message": str(e)}
        return view
    view["stages"]["lexer"] = tokens_to_json(tokens)
    try:
        view["stages"]["parser"] = ast_to_json(Parser(tokens).parse())
    except ParserError as e:
        view["error"] = {"stage": "parser", "message": str(e)}
        return view
    agent = Agent(dry_run=True, echo=False, policy=policy)
    agent.session_clipboard = clipboard
    try:
        ir = agent.compile(text)
    except Exception as e:
        cause = e.__cause__ or e
        view["error"] = {"stage": "semantic", "message": str(cause)}
        return view
    last = agent.last
    view["stages"]["semantic"] = {"warnings": last.warnings, "ast": ast_to_json(last.semantic_ast)}
    view["stages"]["optimizer"] = last.optimizations
    view["stages"]["ir"] = ir
    return view


class CompilerApi:
    def __init__(self, dry_run=True, llm=None, memory=None, speak=True, engine="auto", language="en-IN",
                 whisper_model=None, device="auto", vosk_model=None, policy=None, speaker=None, wake_mode="wake",
                 stream=True):
        self.stream = stream
        self.gate = WakeGate(mode=wake_mode)
        self._lock = threading.Lock()
        self._listen_lock = threading.Lock()
        self._llm_state = (0.0, None)
        self._approve = False
        self._pending = None
        self._pending_text = ""
        self.speech = None
        self.speech_error = None
        self.speech_options = dict(engine=engine, language=language, whisper_model=whisper_model,
                                   device=device, vosk_model=vosk_model)
        self.speaker = speaker if speaker is not None else Speaker(enabled=speak)
        self.speak_enabled = speak
        self.assistant = Assistant(dry_run=dry_run, llm=llm, memory=memory, policy=policy,
                                   confirm=lambda description: self._approve)
        self.assistant.on_thinking = self._say
        self.mode = "dry" if dry_run else "live"

    def status(self):
        llm = self.assistant.llm
        llm_state = None
        if llm is not None:
            checked, ready = self._llm_state
            if ready is None or time.time() - checked > 15:
                ready = bool(llm.available())
                self._llm_state = (time.time(), ready)
            llm_state = {"model": llm.model, "ready": ready}
        engine = self.speech.engine if self.speech else self.speech_options["engine"]
        if engine == "auto":
            import importlib.util
            engine = "whisper" if importlib.util.find_spec("faster_whisper") is not None else "google"
        return {"mode": self.mode, "engine": engine, "language": self.speech_options["language"],
                "llm": llm_state, "memory": self.assistant.memory is not None, "speak": self.speak_enabled,
                "speech_error": self.speech_error,
                "voice_error": self.speaker.error if self.speak_enabled else None,
                "pending": self.assistant.pending.question if self.assistant.pending else None,
                "wake_mode": self.gate.mode, "awake": self.gate.awake,
                "dictating": self.assistant.dictating is not None}

    def set_wake_mode(self, mode):
        self.gate.mode = "always" if mode == "always" else "wake"
        if self.gate.mode == "wake":
            self.gate.sleep()
        return self.status()

    def set_mode(self, mode):
        dry = mode != "live"
        old = self.assistant.agent.executor
        self.assistant.agent.executor = Executor(dry_run=dry, confirm=old.confirm, echo=False, policy=old.policy)
        self.mode = "dry" if dry else "live"
        return self.status()

    def set_speak(self, on):
        self.speak_enabled = bool(on)
        if not on:
            self.speaker.stop()
        return self.status()

    def _say(self, text):
        if self.speak_enabled and text:
            self.speaker.say(text, show=False)

    def listen(self, force=False, fresh=False):
        if fresh and self.speech is not None and hasattr(self.speech, "flush"):
            self.speech.flush()
        if not self._listen_lock.acquire(blocking=False):
            return {"idle": True, "busy": True, "awake": self.gate.awake}
        try:
            return self._listen(force)
        finally:
            self._listen_lock.release()

    def _listen(self, force):
        try:
            if self.speech is None:
                speech = SpeechFrontend(**self.speech_options)
                speech.calibrate()
                if self.stream:
                    speech.start_stream(self.speaker)
                self.speech = speech
            if not self.stream:
                self.speaker.wait(8)
            dictating = self.assistant.dictating is not None
            wait_s = 2.5 if self.stream else None
            t = (self.speech.listen(timeout=wait_s, phrase_limit=25) if dictating
                 else self.speech.listen(timeout=wait_s))
        except SpeechTransient as e:
            return {"error": str(e), "transient": True, "awake": self.gate.awake}
        except (SpeechUnavailable, OSError) as e:
            self.speech_error = str(e)
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Speech problem ({type(e).__name__}: {e}). Listening again.", "transient": True,
                    "awake": self.gate.awake}
        self.speech_error = None
        if t is None:
            return {"idle": True, "awake": self.gate.awake}
        self.gate.hold = self.assistant.dictating is not None
        verdict, rest = self.gate.check(t.raw or t.text, force=force)
        if verdict == "ignored":
            return {"ignored": True, "heard": t.text, "awake": False}
        if verdict == "woke":
            self._say("Yes?")
            return {"woke": True, "awake": True}
        if verdict == "sleep":
            if self.assistant.dictating is not None:
                return {"text": "stop dictation", "raw": t.raw, "alternatives": [], "engine": t.engine,
                        "confidence": t.confidence, "uncertain": False, "latency_ms": t.latency_ms, "awake": True}
            self._say("Okay. Say Hey Compiler when you need me.")
            return {"slept": True, "awake": False}
        text = normalize_transcript(rest) or t.text
        return {"text": text, "raw": t.raw, "alternatives": t.alternatives if rest == (t.raw or t.text) else [],
                "engine": t.engine, "confidence": t.confidence, "uncertain": t.uncertain,
                "latency_ms": t.latency_ms, "notes": list(self.speech.notes), "awake": True}

    def process(self, text, source="typed", alternatives=None, uncertain=False):
        self.gate.touch()
        with self._lock:
            started = time.perf_counter()
            a = self.assistant
            outcome = a.interpret(text, alternatives or [])
            u = outcome.understanding
            report = {
                "said": text,
                "source": source,
                "understood": outcome.text or (u.text if u else text),
                "steps": [{"stage": s.stage, "rule": s.rule, "before": s.before, "after": s.after} for s in u.steps] if u else [],
                "corrections": [list(c) for c in u.corrections] if u else [],
                "kind": outcome.kind,
                "message": outcome.message,
                "via": outcome.source,
                "confirms": [],
                "code": None,
                "stages": {},
                "error": None,
                "results": [],
            }
            compiled_text = outcome.text if outcome.kind in ("ir", "reject", "clarify") else None
            ai_turn = a.pending is not None and a.pending.kind in ("confirm_code", "llm_task")
            if compiled_text and outcome.source != "llm-code" and not ai_turn:
                view = stage_view(compiled_text, a.agent.analyzer.policy, a.agent.session_clipboard)
                report["stages"] = view["stages"]
                if outcome.kind == "reject":
                    report["error"] = view["error"] or {"stage": "lexer", "message": outcome.message}
            if outcome.kind == "ir":
                report["stages"]["ir"] = outcome.ir
                reviewed = outcome.source == "llm-code"
                report["confirms"] = [] if reviewed else [describe(op) for op in outcome.ir if op["args"].get("destructive")]
                self._pending = outcome
                self._pending_text = text
            else:
                self._pending = None
                if outcome.kind == "clarify" and a.pending is not None and a.pending.kind == "confirm_code":
                    report["code"] = {"filename": a.pending.base, "preview": "\n".join(outcome.results)}
                if outcome.kind == "reject" and uncertain:
                    report["message"] = f"I'm not sure I heard that right (\"{text}\"). Please say it again."
                a.record(text, outcome)
                self._say(report["message"])
            report["pending"] = a.pending.question if a.pending else None
            report["ms"] = round((time.perf_counter() - started) * 1000, 1)
            report["ai_ms"] = outcome.timings.get("ai_ms")
            return report

    def execute(self, approved=True):
        with self._lock:
            outcome = self._pending
            if outcome is None:
                return {"kind": "reject", "message": "Nothing is waiting to run.", "results": []}
            self._pending = None
            self._approve = bool(approved)
            steps = [op for op in outcome.ir if op["op"] not in CONTROL]
            if len(steps) >= 4:
                self._say(f"Working on it: {len(steps)} steps.")
            outcome = self.assistant.execute(outcome)
            self.assistant.record(self._pending_text, outcome)
            self._say(outcome.message)
            return {"kind": outcome.kind, "message": outcome.message, "results": list(outcome.results),
                    "error": outcome.error, "pending": self.assistant.pending.question if self.assistant.pending else None}

    def greet(self):
        if self.speak_enabled:
            self.speaker.ready.wait(5)
        if self.speaker.error:
            return {"spoken": False, "error": self.speaker.error}
        self._say("Compiler is ready. Say Hey Compiler, then your command." if self.gate.mode == "wake"
                  else "Compiler is ready. What should I do?")
        return {"spoken": self.speak_enabled}

    def stop(self):
        self.assistant.agent.executor.cancel()
        self.speaker.stop()
        if self.speech is not None and hasattr(self.speech, "flush"):
            self.speech.flush()
        return True

    def memory_summary(self):
        if self.assistant.memory is None:
            return ["Memory is turned off."]
        return self.assistant.memory.summary()
