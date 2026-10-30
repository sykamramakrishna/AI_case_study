import argparse
import sys

from compiler_agent.assistant import CONTROL, Assistant
from compiler_agent.ast_nodes import pretty
from compiler_agent.executor import ExecutionError
from compiler_agent.ir_generator import format_ir
from compiler_agent.nlu import explain
from compiler_agent.speech import Speaker, SpeechFrontend, SpeechTransient, SpeechUnavailable, is_exit, is_yes

BANNER = """
Compiler — voice assistant
  Voice -> Speech-to-Text -> Understanding -> Lexer -> Parser -> Semantic -> Optimizer -> IR -> Executor
  Mode: {mode}   Input: {source}   AI model: {llm}   Memory: {memory}
  Say or type 'stop listening' / 'exit' to quit.  Emergency stop: {stop}
"""


def build_parser():
    p = argparse.ArgumentParser(description="Compile spoken or typed commands into computer actions.")
    p.add_argument("-c", "--command", help="run a single command, then exit")
    p.add_argument("--voice", action="store_true", help="take commands from the microphone")
    p.add_argument("--audio", help="transcribe a .wav/.flac/.aiff recording and run it")
    p.add_argument("--live", action="store_true", help="really control this computer (default is dry run)")
    p.add_argument("--engine", choices=["auto", "google", "whisper", "vosk", "sphinx"], default="auto",
                   help="speech engine: auto (local Whisper if installed, else Google), google, whisper, vosk")
    p.add_argument("--whisper-model", help="Whisper size, e.g. base.en, small.en, medium.en")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="where Whisper runs")
    p.add_argument("--vosk-model", help="path to a downloaded Vosk model folder")
    p.add_argument("--language", default="en-IN", help="language/accent for the Google engine")
    p.add_argument("--llm", action="store_true", help="use the free local AI model through Ollama")
    p.add_argument("--model", default=None, help="Ollama model name (default qwen3:8b)")
    p.add_argument("--no-memory", action="store_true", help="do not read or save memory")
    p.add_argument("--push-to-talk", action="store_true", help="press Enter before each spoken command")
    p.add_argument("--no-optimize", action="store_true", help="skip the optimizer passes")
    p.add_argument("--no-confirm", action="store_true", help="do not ask before risky actions")
    p.add_argument("--speak", action="store_true", help="(default) read results aloud")
    p.add_argument("--no-speak", action="store_true", help="don't read results aloud")
    p.add_argument("--always-listen", action="store_true", help="no wake word: everything you say is a command")
    p.add_argument("-q", "--quiet", action="store_true", help="hide the compiler stages")
    p.add_argument("--check", action="store_true", help="test the microphone and speech recognition, then exit")
    p.add_argument("--ai-check", action="store_true", help="test the local AI model (Ollama), then exit")
    p.add_argument("--ollama-host", default="http://localhost:11434", help="where Ollama is listening")
    return p


def check_voice(args):
    print("Voice setup check\n")
    try:
        import speech_recognition as sr
        print(f"[ok]   SpeechRecognition {sr.__version__} installed")
    except ImportError:
        print("[FAIL] SpeechRecognition missing  ->  py -3.12 -m pip install SpeechRecognition")
        return 1
    try:
        import pyaudio
        print(f"[ok]   PyAudio {pyaudio.__version__} installed")
    except ImportError:
        print("[FAIL] PyAudio missing  ->  py -3.12 -m pip install pyaudio")
        return 1
    try:
        names = sr.Microphone.list_microphone_names()
    except Exception as e:
        print(f"[FAIL] Could not list microphones: {e}")
        return 1
    if not names:
        print("[FAIL] No microphone found. Plug one in or enable it in Windows sound settings.")
        return 1
    print(f"[ok]   {len(names)} audio device(s) found, using the default microphone")
    try:
        speech = SpeechFrontend(engine=args.engine, language=args.language, whisper_model=args.whisper_model,
                                device=args.device, vosk_model=args.vosk_model)
        print(f"[ok]   speech engine: {speech.engine}")
        print("\nCalibrating, stay quiet for a second...")
        speech.calibrate()
        print("Now say: 'open notepad'")
        heard = speech.listen()
        for note in speech.notes:
            print(f"[info] {note}")
    except SpeechUnavailable as e:
        print(f"[FAIL] {e}")
        return 1
    except OSError as e:
        print(f"[FAIL] Microphone error: {e}. Check Settings > Privacy & security > Microphone.")
        return 1
    if not heard:
        print("[FAIL] Heard nothing. Speak louder/closer, or check the default input device in Sound settings.")
        return 1
    print(f"[ok]   Heard: '{heard.text}'  ({heard.engine}, {heard.latency_ms} ms)")
    if args.llm:
        from compiler_agent.llm import OllamaClient, pick_model
        client = OllamaClient(model=pick_model(args.model))
        print(f"[{'ok' if client.available() else 'FAIL'}]   Ollama model {client.model} "
              f"{'ready' if client.available() else 'not available: install Ollama and run: ollama pull ' + client.model}")
    print("\nVoice works. Start with:  py -3.12 main.py --voice --live")
    return 0


def check_ai(args):
    import json
    import time
    import urllib.request
    from compiler_agent.llm import FALLBACK_MODEL, LLMUnavailable, OllamaClient, pick_model
    model = pick_model(args.model, args.ollama_host)
    print("AI model check\n")
    try:
        with urllib.request.urlopen(args.ollama_host + "/api/tags", timeout=5) as resp:
            names = [m.get("name", "") for m in json.loads(resp.read().decode()).get("models", [])]
    except Exception as e:
        print(f"[FAIL] Ollama is not running at {args.ollama_host} ({e}).")
        print("       Install it from https://ollama.com/download, then open the Ollama app (llama icon in the tray).")
        return 1
    print(f"[ok]   Ollama is running. Downloaded models: {', '.join(names) or 'none'}")
    if model not in names and f"{model}:latest" not in names:
        print(f"[FAIL] Model '{model}' is not downloaded. Run:  ollama pull {model}")
        if model != FALLBACK_MODEL:
            print(f"       (smaller and faster alternative: ollama pull {FALLBACK_MODEL}, then add --model {FALLBACK_MODEL})")
        return 1
    print(f"[ok]   Model '{model}' is downloaded")
    client = OllamaClient(model=model, host=args.ollama_host)
    tests = ["jot down buy milk in the notepad app", "what does a lexer do", "create a python project"]
    ok = 0
    for i, text in enumerate(tests):
        started = time.perf_counter()
        try:
            proposal = client.translate(text)
        except LLMUnavailable as e:
            print(f"[FAIL] {e}")
            return 1
        seconds = time.perf_counter() - started
        shown = proposal.text if proposal else "(unusable reply)"
        note = " (first request also loads the model into memory)" if i == 0 else ""
        print(f"[{'ok' if proposal else 'FAIL'}]   {text!r} -> {proposal.kind if proposal else '-'}: {shown}  "
              f"[{seconds:.1f} s{note}]")
        ok += proposal is not None
    if ok == len(tests):
        print(f"\nAI works with {model}. Start with:  py -3.12 app.py --llm   (or main.py --voice --live --llm)")
        return 0
    return 1


def make_confirm(args, speech, speaker):
    if args.no_confirm or not args.live:
        return None

    def typed(description):
        answer = input(f"  Type y to {description}, or n to skip: ")
        return is_yes(answer) or answer.strip().lower() == "y"

    def confirm(description):
        if speech is None:
            return typed(description)
        speaker.say(f"Should I {description}? Say yes or no.")
        speaker.wait()
        for attempt in range(2):
            print("  Listening for yes / no...")
            try:
                answer = speech.listen(timeout=8, phrase_limit=4)
            except SpeechUnavailable:
                answer = None
            print(f"  heard: {answer.text if answer else '(nothing)'}")
            if answer:
                return is_yes(answer.text)
            if attempt == 0:
                speaker.say("I didn't catch that. Please say yes or no.")
                speaker.wait()
        print("  Still couldn't hear an answer.")
        return typed(description)

    return confirm


def show_stages(assistant):
    last = assistant.agent.last
    if last is None:
        return
    print("\n--- compiler stages " + "-" * 44)
    print("tokens:", last.tokens)
    print(pretty(last.semantic_ast) if last.semantic_ast is not None else "")
    for w in last.warnings:
        print(f"warning: {w}")
    for o in last.optimizations:
        print(f"optimizer: {o}")
    print(format_ir(last.ir))


def present(assistant, outcome, transcript, args, speaker):
    u = outcome.understanding
    if u is not None and u.text != (u.original or "").strip():
        print(f"Understood as: \"{u.text}\"")
        if not args.quiet:
            print(explain(u))
    if outcome.kind == "ir" or (outcome.kind == "failed" and outcome.ir):
        if not args.quiet:
            show_stages(assistant)
        if outcome.source in ("corrected", "alternative"):
            print(f"(note: used the {'corrected' if outcome.source == 'corrected' else 'alternative'} hearing)")
    for line in outcome.results if outcome.kind == "clarify" else []:
        print(line)
    message = outcome.message
    if outcome.kind == "reject" and transcript is not None and transcript.uncertain:
        message = f"I'm not sure I heard that right (\"{transcript.text}\"). Please say it again."
    t = outcome.timings
    parts = []
    if transcript is not None:
        parts.append(f"hearing {transcript.latency_ms} ms")
    if "understand_ms" in t:
        parts.append(f"compiler {max(t['understand_ms'], 0)} ms")
    if "ai_ms" in t:
        parts.append(f"AI {t['ai_ms'] / 1000:.1f} s")
    if "run_ms" in t:
        parts.append(f"running {t['run_ms']} ms")
    if parts:
        print("Time: " + ", ".join(parts))
    label = {"dictation": "Dictation", "ir": "Done", "answer": "Answer", "clarify": "Question", "reject": "Can't do that",
             "failed": "Failed", "cancelled": "Cancelled", "memory": "Memory"}.get(outcome.kind, outcome.kind)
    print(f"{label}: {message}")
    speaker.say(message, show=False)


def run_one(assistant, text, args, speaker, transcript=None):
    print("\n" + "=" * 70)
    print(f"You said: \"{text}\"" + (f"   ({transcript.engine}, {transcript.latency_ms} ms"
                                     + (f", confidence {transcript.confidence:.0%}" if transcript.confidence else "")
                                     + ")" if transcript else ""))
    if transcript and transcript.alternatives:
        print(f"Other hearings: {transcript.alternatives}")
    try:
        outcome = assistant.handle(text, transcript.alternatives if transcript else None)
    except KeyboardInterrupt:
        assistant.agent.executor.cancel()
        print("Stopped.")
        speaker.say("Stopped.", show=False)
        return
    except ExecutionError as e:
        print(f"Failed: {e}")
        return
    present(assistant, outcome, transcript, args, speaker)


def install_stop_hotkey(assistant, speaker):
    try:
        from pynput import keyboard
    except ImportError:
        return "Ctrl+C (install pynput for Ctrl+Alt+S)"

    def stop():
        assistant.agent.executor.cancel()
        speaker.stop()
        print("\n[emergency stop requested]")

    listener = keyboard.GlobalHotKeys({"<ctrl>+<alt>+s": stop})
    listener.daemon = True
    listener.start()
    return "Ctrl+Alt+S"


def voice_loop(assistant, speech, speaker, args):
    from compiler_agent.speech import normalize_transcript
    from compiler_agent.wake import WakeGate
    gate = WakeGate(mode="always" if (args.always_listen or args.push_to_talk) else "wake")
    print("Calibrating for background noise, stay quiet for a second...")
    speech.calibrate()
    if not args.push_to_talk:
        speech.start_stream(speaker)
    for note in speech.notes:
        print(f"[info] {note}")
    if speaker.error:
        print(f"[warn] {speaker.error}")
    if gate.mode == "wake":
        print("\nSay 'Hey Compiler' (or 'Hey Computer') to wake me. Say 'stop' to put me back to sleep.")
        speaker.say("Compiler is ready. Say Hey Compiler, then your command.", show=False)
    else:
        speaker.say("Compiler is ready. What should I do?", show=False)
    was_awake = None
    while True:
        if args.push_to_talk:
            speaker.wait()
        if args.push_to_talk and input("\nPress Enter and speak (or type q to quit): ").strip().lower() == "q":
            return
        prompt = assistant.pending.question if assistant.pending else None
        gate.hold = assistant.dictating is not None or prompt is not None
        if gate.awake != was_awake:
            print("\nListening..." if gate.awake else "\nSleeping... say 'Hey Compiler'")
            was_awake = gate.awake
        if prompt:
            print(f"  (answering: {prompt})")
        try:
            heard = speech.listen(phrase_limit=25) if assistant.dictating is not None else speech.listen()
        except SpeechTransient as e:
            print(f"(network hiccup: {e}; listening again)")
            continue
        except SpeechUnavailable as e:
            print(f"SPEECH ERROR: {e}")
            return
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"(speech problem: {type(e).__name__}: {e}; listening again)")
            continue
        if not heard:
            continue
        if is_exit(heard.text) and heard.text.lower().strip(" .!") in ("exit", "quit", "exit program", "close the assistant"):
            speaker.say("Goodbye.")
            speaker.wait()
            return
        verdict, rest = gate.check(heard.raw or heard.text)
        if verdict == "ignored":
            continue
        if verdict == "woke":
            print("(awake)")
            speaker.say("Yes?")
            continue
        if verdict == "sleep":
            if assistant.dictating is not None:
                run_one(assistant, "stop dictation", args, speaker, heard)
                continue
            speaker.say("Okay. Say Hey Compiler when you need me.")
            continue
        heard.text = normalize_transcript(rest) or heard.text
        run_one(assistant, heard.text, args, speaker, heard)
        gate.touch()


def text_loop(assistant, speaker, args):
    while True:
        try:
            prompt = f"\n{assistant.pending.question}\nanswer> " if assistant.pending else "\ncommand> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if is_exit(line):
            return
        if line.strip():
            run_one(assistant, line, args, speaker)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.ai_check:
        return check_ai(args)
    if args.check:
        return check_voice(args)
    speaker = Speaker(enabled=not args.no_speak)
    speech = None
    if args.voice or args.audio:
        try:
            speech = SpeechFrontend(engine=args.engine, language=args.language, whisper_model=args.whisper_model,
                                    device=args.device, vosk_model=args.vosk_model)
        except SpeechUnavailable as e:
            print(f"SPEECH ERROR: {e}")
            return 1
    llm = None
    if args.llm:
        from compiler_agent.llm import OllamaClient, pick_model
        llm = OllamaClient(model=pick_model(args.model, args.ollama_host), host=args.ollama_host)
        llm.warm_up_async()
        if not llm.available():
            print(f"[info] Ollama model '{llm.model}' is not available yet. Install Ollama from ollama.com and run: "
                  f"ollama pull {llm.model}. Continuing; AI requests will report the problem.")
    memory = None
    if not args.no_memory:
        from compiler_agent.memory_store import Memory
        memory = Memory()

    def progress(outcome):
        steps = [op for op in outcome.ir if op["op"] not in CONTROL]
        if len(steps) >= 4:
            speaker.say(f"Working on it: {len(steps)} steps.")

    try:
        assistant = Assistant(dry_run=not args.live, optimize=not args.no_optimize, llm=llm, memory=memory,
                              confirm=make_confirm(args, speech if args.voice else None, speaker),
                              on_progress=progress)
    except ExecutionError as e:
        print(f"ERROR: {e}")
        return 1
    assistant.on_thinking = lambda message: speaker.say(message, show=False)
    stop_key = install_stop_hotkey(assistant, speaker)

    if args.audio:
        try:
            heard = speech.transcribe_file(args.audio)
        except (SpeechUnavailable, OSError, ValueError) as e:
            print(f"SPEECH ERROR: {e}")
            return 1
        if heard:
            run_one(assistant, heard.text, args, speaker, heard)
        else:
            print("Heard: (nothing recognised)")
        speaker.wait()
        return 0
    if args.command:
        run_one(assistant, args.command, args, speaker)
        speaker.wait()
        return 0

    mode = "LIVE (controls this computer)" if args.live else "DRY RUN (nothing is touched)"
    source = f"microphone ({speech.engine})" if args.voice else "keyboard"
    print(BANNER.format(mode=mode, source=source, llm=llm.model if llm else "off (add --llm)",
                        memory="on" if memory else "off", stop=stop_key))
    try:
        if args.voice:
            voice_loop(assistant, speech, speaker, args)
        else:
            text_loop(assistant, speaker, args)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
