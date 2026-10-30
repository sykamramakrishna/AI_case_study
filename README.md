# Compiler Voice Assistant

A voice assistant that controls your computer through a real compiler pipeline. Spoken words never run directly. They are understood, compiled, type-checked and optimised first, and then executed by a small virtual machine. Everything is free, and everything except the optional Google speech engine runs locally.

```
Microphone ─► Speech-to-text ─► Understanding ─► Lexer ─► Parser ─► Semantic ─► Optimizer ─► IR ─► Executor ─► Computer
             (Whisper / Google   (cleanup, self-   (tokens) (AST)    (types,     (folding,   (jumps, (VM with
              / Vosk)             corrections,                       data-flow,  unrolling,  labels) confirm,
                                  rewrites, mis-                     safety)     peephole)           cancel)
                                  hearing fixes)
                     ▲                    │ can't understand?
                     │                    ▼
              Conversation ◄── optional local AI (Ollama, qwen3:8b) proposes a command,
              state + memory    which goes through the same compiler checks and needs your yes
```

## Quick start (Windows)

```
py -3.12 -m pip install -r requirements.txt
py -3.12 run_tests.py                     # all tests and the accuracy evaluation
py -3.12 main.py                          # type commands, safe dry run
py -3.12 main.py --voice                  # speak commands, safe dry run
py -3.12 main.py --voice --live --speak   # really control the PC, with spoken replies
```

Or double-click **start_voice.bat**, or **start_voice_ai.bat** for the version with the AI model.

### Desktop app (Compiler interface)

```
py -3.12 -m pip install pywebview
py -3.12 app.py          # or double-click start_app.bat
py -3.12 app.py --llm    # with the local AI model, or start_app_ai.bat
```

The app greets you and listens **hands-free** behind a wake word: say **"Hey Compiler"** (or "Hey Computer"), then your command. It stays awake for follow-ups, and "stop" puts it back to sleep. You can answer its Yes/No questions by voice, and "stop listening" pauses it. The window shows the compiler working as you speak:
- the orb (click it or press **Ctrl+Space** to talk)
- what was heard versus what was understood, with every fix applied
- the 7-stage pipeline: Understand → Lexer → Parser → Semantic → Optimizer → IR → Execute
- an inspector for each stage
- confirmation dialogs for risky steps, and a review dialog for AI-written code
- a Dry run / Live switch (Live asks first), a **Stop** button and **Esc**

On Windows it uses Microsoft Edge WebView2, which is already part of Windows 10 and 11. The page is in `ui/index.html`. `py -3.12 ui\build_preview.py` makes a standalone browser preview that replays recorded runs.

### Optional: local, offline speech recognition (recommended)

```
py -3.12 -m pip install -r requirements-local-ai.txt
py -3.12 main.py --check
```

- `--engine auto` (the default) uses Google's Indian-English recogniser, which is fast and accurate without a GPU. If Google is unreachable, it switches to Whisper locally. Use `--engine whisper` to stay fully offline.
- The first run downloads the model once: small.en is about 470 MB, base.en about 145 MB.
- On an NVIDIA GPU it uses small.en. If CUDA isn't set up, it automatically uses base.en on the CPU.
- GPU use needs the CUDA 12 cuBLAS and cuDNN 9 libraries, which is optional.
- Commands are biased towards app names and the command vocabulary through Whisper's prompt.

### Optional: free local AI model for free-form requests, questions and code

1. Install **Ollama** from ollama.com (free and open source).
2. Run `ollama pull qwen3:8b`. This is about 5 GB, Apache-2.0 licensed, and fits 16 GB of RAM. For a faster, smaller option use `qwen3:4b`.
3. Start with `--llm`, for example `py -3.12 main.py --voice --live --llm`.

The model is only used when the grammar can't understand you. Everything it proposes goes through the compiler:
- A safe command runs straight away, and the reply shows "understood as …".
- Risky steps (closing apps, deleting, running scripts) still ask first.
- Code is shown for review before it is saved.
- `--model` is optional: the app picks whichever model you have downloaded, and loads it into memory at startup.

### Emergency stop

- **Ctrl+Alt+S** stops the current task between steps. This needs pynput.
- **Ctrl+C** works in the console.
- Moving the mouse into a screen corner aborts pyautogui (its failsafe).

## What you can say

| Area | Examples |
|---|---|
| Apps | open word, launch the chrome browser, fire up vs code, switch to excel, close it, minimize the window |
| Websites | open youtube, go to github.com, visit vtop, show me linkedin |
| Typing | type hello world, write my name is Pavanji in notepad, type quote open the door unquote |
| Files and folders | create notes.txt, create a python file called sorting, create folder lab reports, write buy milk into notes.txt, delete notes.txt |
| Code | run hello.py, run the tests, fix the errors (needs the AI model) |
| Clipboard | take a screenshot and paste it into word, copy everything, select all |
| Keys and mouse | press control s, hit the enter key, press tab 3 times, click on Save, scroll down twice, refresh the page, undo that |
| Search | search for compiler notes, google machine learning, play arijit singh songs on youtube |
| Questions | what time is it, what's the date, what is 25 into 4, calculate 15 percent of 2 lakh |
| Volume and system | turn up the volume, mute the sound, lock my computer |
| Logic | if notes.txt exists then open notes.txt otherwise create notes.txt; repeat 5 times press down end repeat |
| Conversation | "delete" → *Which file?* → "notes.txt"; "open chrome" → "no, I meant firefox"; "do it again" |
| Memory | remember that my project folder is D:\cn → "open my project folder"; what do you remember; forget project folder; stop saving my history |
| YouTube and media | play kesariya song (plays the top video); pause the song; next song |
| Dictation and writing | start dictation in notepad … stop dictation; write a paragraph about compilers in notepad (AI) |
| WhatsApp (desktop app) | save Rahul's number as 98765 43210 → then chats open exactly; without a number it searches the name. |
| WhatsApp phrasings | open whatsapp chat with Rahul; message Rahul saying I'll be late; send happy birthday to Priya on whatsapp. Sending always asks first. |

It also copes with natural speech:
- fillers: "um open uh notepad"
- politeness: "can you please…"
- self-corrections: "open chrome no wait open notepad", "wait 5 no 10 seconds"
- common mishearings: "tape hello" → type, "clothes chrome" → close, "you tube" → youtube, "v. s. code" → vscode

Dictated text after *type*, *search* or *calculate* is never rewritten.

## Measured results

Accuracy of turning a transcript into the right compiled actions, measured with `py -3.12 eval/evaluate.py --set all`:

| Test set | Utterances | Before (old compiler only) | After |
|---|---|---|---|
| Dev (used while improving) | 136 | 32.4 % | 100 % |
| Held-out (read only after tuning) | 35 | 31.4 % | 100 % |
| **Blind (new phrasings, first run)** | 45 | — | **91.1 %**, then 97.8 % after fixes |

- **Before** is the original compiler run on its own. See `eval/baseline.txt`.
- **The blind first-run score is the honest estimate** for phrasings the system hasn't seen. See `eval/blind_first_run.txt`. The remaining blind "miss" is "open crow": it asks "Did you mean chrome?" instead of guessing, which is intended.
- These numbers measure understanding of text. They do not measure speech recognition.
- **To measure speech recognition on your own voice and microphone:**

```
py -3.12 eval\asr_benchmark.py record              # read 30 commands aloud, saved as WAV files
py -3.12 eval\asr_benchmark.py run --engines google,whisper
```

It reports word error rate, command accuracy and latency for each engine. Record a second session with background noise using `--folder eval\recordings\noisy`.

## Free-only components

| Component | Licence and cost | Runs | Category |
|---|---|---|---|
| Compiler, understanding, memory (SQLite), calculator | your code, Python standard library | local | A: free, local |
| faster-whisper + Whisper models | MIT | local, offline | A |
| Vosk (optional) | Apache-2.0 | local, offline | A |
| Ollama + qwen3:8b / qwen3:4b (optional) | free open source; Qwen3 is Apache-2.0 | local, offline | A |
| pyttsx3 (Windows SAPI voices) | MPL-2.0, built-in voices | local | A |
| pyautogui, pywin32, psutil, pynput, Pillow, pytesseract | free licences | local | A |
| Google Web Speech through SpeechRecognition | free, unofficial, rate-limited, online | cloud | B: kept only as a fallback |

No paid APIs, accounts or credit cards are needed.

## How the new understanding layer works (`compiler_agent/nlu.py`, `assistant.py`)

1. **Capture** (`speech.py`). The microphone is calibrated for background noise. Whisper's built-in voice-activity filter drops silence.
2. **Recognition.** The engine returns the best text, any alternatives, its confidence and an "uncertain" flag. Text that just echoes Whisper's vocabulary prompt is rejected, so the model can't invent a command.
3. **Normalisation.** Removes wake words ("hey computer"), turns "notes dot txt" into notes.txt, joins spelled letters ("v. s." → vs) and trims trailing punctuation.
4. **Contextual cleanup.** Removes fillers and politeness, resolves self-corrections, and joins split names ("you tube" → youtube). Every rewrite rule is logged, and the **original transcript is kept**.
5. **Compile.** If the grammar accepts the text, it's done. If not:
   - The recogniser's other hearings are tried first.
   - Then mishearing fixes are tried on command words only. These use a phonetic code, edit distance and an ASR confusion list.
   - A fix is kept **only if the result compiles**. A low-confidence fix becomes a question ("Did you mean…?").
6. **Missing information becomes a question.** The answer to the next turn fills the gap.
7. **Optional AI model.** Its proposal is compiled, validated and then confirmed by you.
8. **Execution.** Uses the virtual machine, with:
   - confirmation for risky actions
   - cancellation between steps
   - timeouts on scripts
   - checks that files were really written and created
   - honest partial-failure reports ("I completed 1 step, then stopped: …")

## Status

**Working, and tested here: 173 automated tests, 33 browser checks of the interface, and the 216-utterance evaluation**
- Smooth listening: the microphone records continuously on a background thread and recognition runs in parallel, so the next command is captured while the current one runs. Phrases captured while Compiler is talking are discarded (no self-hearing). Stop/Esc drops queued speech; speech older than 20 s is ignored. AI calls are capped (35 s) so nothing hangs.
- Original compiler pipeline: all 60 original-suite tests still pass, and dry-run mode is unchanged.
- Understanding layer: fillers, politeness, self-corrections, paraphrases, split names, mishearing correction, choosing between n-best hearings, and protection of dictated text.
- Conversation: follow-up questions for missing details, "no, I meant…", "close it" / "run it", "do it again", cancel.
- New actions:
  - folders, writing text into files, running scripts, running tests with error explanations
  - calculator, time and date
  - YouTube search, minimise/maximise, lock screen, refresh, undo, new tab
- Safety:
  - refuses shut down, restart and log off
  - refuses bulk deletes and wildcards
  - allowed-folder policy for file changes
  - unknown apps are never killed
  - confirmation before closing apps, deleting, running scripts or writing AI-generated code
  - fix attempts limited to 3
  - step limit in the virtual machine
- Memory: SQLite shortcuts, notes and optional history, with "what do you remember", "forget…" and "forget everything". Passwords, OTPs and card numbers are never stored.
- Speech logic: Whisper, Google and Vosk handling, fallback, confidence flags, prompt-echo rejection. Tested with stand-in models, because model downloads are blocked in the build environment.
- AI model client: tested against a local fake Ollama server, covering structured JSON output, a retry on bad JSON, and model-missing and server-down errors. The full "Create a Python project" → clarify → write code → run → fix → run conversation is tested with a scripted stand-in model.
- Live file and script tools were run for real, on Linux.

- Desktop interface: the real `ui/index.html` was driven in Chromium against the real Python bridge, with the AI model scripted, and passed 23 checks:
  - status chips
  - corrections shown
  - all pipeline stages
  - follow-up questions and answers
  - confirmation dialogs and declines
  - refusals
  - error shown on the right stage
  - a voice turn
  - AI question → code review → save
  - switching to Live and running a real action
  - memory and history
  - no horizontal scroll at 400 px
  - no page errors
- The bridge contract has 10 tests.

**Incomplete, or not tested on your hardware yet**
- The pywebview desktop window itself: it can't open in the build environment, which has no display. pywebview's API was checked against the installed package.
- Real microphone accuracy of Whisper, Google or Vosk on your voice. Run `eval/asr_benchmark.py`.
- The real qwen3 model's answer quality and latency. Only the client and the safety flow are tested.
- Windows-specific actions: window focus, Word, volume, lock, screenshot to clipboard. These were written for Windows but only partly run under Linux.
- Spoken-reply interruption (stopping text-to-speech mid-sentence). pyttsx3's stop is platform-dependent.
- Mixed-language speech (Hinglish and others) was out of scope, as you chose English only.

**Failed tests:** none at the time of writing.

**Known limitations**
- In one dictated sentence, saying "and" followed by a command word ends the dictation, as in "type bread and make tea". Use "quote … unquote" for such text.
- Clicking by name needs the Tesseract OCR program installed.
- Questions beyond time, date and arithmetic need the local AI model.
- The test sets were written by the developer, so real users will find phrasings that fail. Please add them to `eval/utterances_*.json`.

**Manual setup**
- PyAudio: `pip install pyaudio`.
- Microphone permission: Windows Settings → Privacy → Microphone.
- Optional: faster-whisper, Ollama + `ollama pull qwen3:8b`, Tesseract.

## Project layout

```
app.py                      desktop app (pywebview window + JS bridge)
ui/index.html               Compiler interface; ui/build_preview.py makes a browser preview
main.py                     CLI: voice, text, audio file, one-shot, --check, --ai-check
compiler_agent/
  speech.py                 capture, recognition engines, normalisation, text-to-speech
  nlu.py                    understanding stages (cleanup, self-corrections, rewrites, mishearing fixes)
  assistant.py              conversation state, follow-up questions, references, AI model fallback, memory commands
  llm.py                    Ollama client with JSON schema output (optional)
  memory_store.py           SQLite memory with sensitive-data filter
  policy.py                 allowed folders, timeouts
  calc.py                   safe arithmetic evaluator (no eval)
  lexer.py parser.py ast_nodes.py semantic_analyzer.py optimizer.py ir_generator.py
  executor.py backends.py   compiler and virtual machine (original architecture, extended)
  registry.py agent.py serialize.py
eval/                       evaluation sets, evaluate.py, asr_benchmark.py, baseline and blind results
test_*.py, run_tests.py     test suites
```
