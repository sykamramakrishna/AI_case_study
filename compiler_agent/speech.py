import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

EXIT_PHRASES = {"stop listening", "exit", "quit", "goodbye", "bye", "exit program", "close the assistant"}
YES_WORDS = {"yes", "yeah", "yep", "sure", "confirm", "ok", "okay", "go ahead", "do it", "yes please"}
WAKE_PREFIX = re.compile(r"^\s*(hey\s+)?(computer|compiler|assistant|jarvis)[\s,]+", re.IGNORECASE)

APP_WORDS = ("Notepad, Chrome, Microsoft Word, Excel, PowerPoint, VS Code, File Explorer, Calculator, "
             "YouTube, WhatsApp, GitHub, LinkedIn, Gmail, VTOP, Spotify, Firefox, Edge")
COMMAND_PROMPT = (f"Computer voice commands. Open {APP_WORDS}. Type hello world. Take a screenshot and paste it "
                  "into Word. Press control S, tab, enter, escape. Scroll down. Volume up. Create folder projects. "
                  "Create notes.txt. Search for compiler design. What is 25 times 4.")


class SpeechUnavailable(Exception):
    pass


class SpeechTransient(SpeechUnavailable):
    pass


@dataclass
class Transcript:
    text: str
    alternatives: List[str] = field(default_factory=list)
    engine: str = ""
    confidence: Optional[float] = None
    uncertain: bool = False
    raw: str = ""
    latency_ms: float = 0.0

    def __str__(self):
        return self.text


def normalize_transcript(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = WAKE_PREFIX.sub("", text)
    text = re.sub(r"(\w)\s+dot\s+(\w{1,6})\b", r"\1.\2", text, flags=re.IGNORECASE)
    text = re.sub(r"(\w)\s+underscore\s+(\w)", r"\1_\2", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[.!?]+$", "", text).strip()
    return text


def is_exit(text):
    return normalize_transcript(text).lower().strip(" .!") in EXIT_PHRASES


def is_yes(text):
    words = normalize_transcript(text).lower()
    return any(w == words or words.startswith(w + " ") for w in YES_WORDS)


def looks_like_prompt_echo(text):
    low = text.lower().strip(" .")
    return len(low) > 25 and low in COMMAND_PROMPT.lower()


class SpeechFrontend:
    def __init__(self, engine="auto", language="en-IN", whisper_model=None, device="auto",
                 vosk_model=None, timeout=5, phrase_limit=10, request_timeout=4):
        try:
            import speech_recognition as sr
        except ImportError as e:
            raise SpeechUnavailable("Voice input needs SpeechRecognition: pip install SpeechRecognition pyaudio") from e
        self.sr = sr
        self.language = language
        self.whisper_model_name = whisper_model
        self.device = device
        self.vosk_model_path = vosk_model
        self.timeout = timeout
        self.phrase_limit = phrase_limit
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.7
        self.recognizer.non_speaking_duration = 0.4
        self.recognizer.phrase_threshold = 0.2
        self.recognizer.operation_timeout = request_timeout
        self.base_energy = None
        self._mic = None
        self._source = None
        self._mic_lock = threading.Lock()
        self._google_retry_at = 0.0
        self._whisper = None
        self._model_lock = threading.Lock()
        self._vosk = None
        self._stream = None
        self._speaker = None
        self.stream_phrase_limit = phrase_limit
        self.notes = []
        self.engine = self._pick_engine(engine)

    def _pick_engine(self, engine):
        import importlib.util
        self.local_available = importlib.util.find_spec("faster_whisper") is not None
        if engine != "auto":
            return engine
        return "google"

    def _microphone(self):
        try:
            return self.sr.Microphone(sample_rate=16000)
        except (AttributeError, OSError) as e:
            raise SpeechUnavailable("No microphone available (is PyAudio installed?): pip install pyaudio") from e

    def _open(self):
        if self._source is None:
            self._mic = self._microphone()
            self._source = self._mic.__enter__()
        return self._source

    def close(self):
        if self._mic is not None:
            try:
                self._mic.__exit__(None, None, None)
            except Exception:
                pass
        self._mic = self._source = None

    def calibrate(self, seconds=0.8):
        with self._mic_lock:
            source = self._open()
            self.recognizer.adjust_for_ambient_noise(source, duration=seconds)
        self.recognizer.energy_threshold = max(self.recognizer.energy_threshold, 120)
        self.base_energy = self.recognizer.energy_threshold

    def _guard_energy(self):
        base = self.base_energy
        if base and self.recognizer.energy_threshold > max(base * 4, 1500):
            self.recognizer.energy_threshold = base * 1.5

    def capture(self, timeout=None, phrase_limit=None):
        with self._mic_lock:
            self._guard_energy()
            for attempt in range(2):
                try:
                    source = self._open()
                    return self.recognizer.listen(source, timeout=timeout or self.timeout,
                                                  phrase_time_limit=phrase_limit or self.phrase_limit)
                except self.sr.WaitTimeoutError:
                    return None
                except (OSError, AttributeError) as e:
                    self.close()
                    if attempt:
                        raise SpeechUnavailable(f"the microphone stopped working ({e}). Check it is plugged in.") from e

    def listen(self, timeout=None, phrase_limit=None) -> Optional[Transcript]:
        if self._stream is not None:
            self.stream_phrase_limit = phrase_limit or self.phrase_limit
            return self.next_transcript(timeout or self.timeout)
        audio = self.capture(timeout, phrase_limit)
        if audio is None:
            return None
        return self.transcribe(audio)

    def start_stream(self, speaker=None, workers=2, max_age=20.0):
        if self._stream is not None:
            return
        from concurrent.futures import ThreadPoolExecutor
        self._speaker = speaker
        self._max_age = max_age
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self._futures = queue.Queue()
        self._stream = threading.Event()
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()

    def stop_stream(self):
        if self._stream is None:
            return
        self._stream.set()
        self._stream_thread.join(timeout=3)
        self._pool.shutdown(wait=False)
        self._stream = None

    def _speaker_busy_since(self, since):
        sp = self._speaker
        if sp is None:
            return False
        return sp.speaking or getattr(sp, "last_active", 0.0) > since

    def _drain(self, source, seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                source.stream.read(source.CHUNK)
            except Exception:
                return

    def _stream_loop(self):
        stop = self._stream
        while not stop.is_set():
            if self._speaker is not None and self._speaker.speaking:
                time.sleep(0.05)
                continue
            started = time.time()
            with self._mic_lock:
                try:
                    source = self._open()
                    if self._speaker is not None and time.time() - getattr(self._speaker, "last_active", 0.0) < 0.6:
                        self._drain(source, 0.35)
                        continue
                    self._guard_energy()
                    audio = self.recognizer.listen(source, timeout=1,
                                                   phrase_time_limit=self.stream_phrase_limit or self.phrase_limit)
                except self.sr.WaitTimeoutError:
                    continue
                except (OSError, AttributeError) as e:
                    self.close()
                    self._futures.put((time.time(), None, SpeechUnavailable(
                        f"the microphone stopped working ({e}). Check it is plugged in.")))
                    time.sleep(1.0)
                    continue
            if self._speaker_busy_since(started):
                continue
            self._futures.put((time.time(), self._pool.submit(self.transcribe, audio), None))

    def next_transcript(self, timeout=5.0) -> Optional[Transcript]:
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            try:
                captured, future, error = self._futures.get(timeout=max(0.05, left))
            except queue.Empty:
                return None
            if error is not None:
                raise error
            if time.time() - captured > self._max_age:
                future.cancel()
                continue
            result = future.result(timeout=self.recognizer.operation_timeout + 6)
            if result is not None:
                return result
            if time.time() >= deadline:
                return None

    def flush(self):
        if self._stream is None:
            return
        while True:
            try:
                _, future, _ = self._futures.get_nowait()
            except queue.Empty:
                return
            if future is not None:
                future.cancel()

    def transcribe_file(self, path) -> Optional[Transcript]:
        with self.sr.AudioFile(path) as source:
            audio = self.recognizer.record(source)
        return self.transcribe(audio)

    def transcribe(self, audio) -> Optional[Transcript]:
        started = time.perf_counter()
        retry_at = getattr(self, "_google_retry_at", 0.0)
        if retry_at and time.time() > retry_at and self.engine == "whisper":
            self.engine, self._google_retry_at = "google", 0.0
        try:
            result = getattr(self, f"_recognize_{self.engine}")(audio)
        except AttributeError as e:
            raise SpeechUnavailable(f"Unknown speech engine '{self.engine}'") from e
        except SpeechUnavailable as e:
            if self.engine == "google":
                if not getattr(self, "local_available", False):
                    raise SpeechTransient(str(e)) from e
                self.notes.append(f"Google unavailable ({e}); using offline Whisper for a minute")
                self.engine = "whisper"
                self._google_retry_at = time.time() + 60
                result = self._recognize_whisper(audio)
            else:
                self.notes.append(f"{self.engine} failed ({e}); falling back to Google")
                self.engine = "google"
                result = self._recognize_google(audio)
        if result is None:
            return None
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        result.raw = result.text
        result.text = normalize_transcript(result.text)
        result.alternatives = [normalize_transcript(a) for a in result.alternatives if normalize_transcript(a)]
        result.alternatives = [a for a in dict.fromkeys(result.alternatives) if a != result.text]
        return result if result.text else None

    def _recognize_google(self, audio):
        try:
            data = self.recognizer.recognize_google(audio, language=self.language, show_all=True)
        except self.sr.UnknownValueError:
            return None
        except (self.sr.RequestError, TimeoutError, OSError) as e:
            raise SpeechUnavailable(
                f"the internet is slow or offline, so Google speech didn't answer ({e}). Please say it again."
            ) from e
        if not data or not isinstance(data, dict) or not data.get("alternative"):
            return None
        alts = data["alternative"]
        best = alts[0]
        conf = best.get("confidence")
        return Transcript(text=best["transcript"], alternatives=[a["transcript"] for a in alts[1:]],
                          engine="google", confidence=conf, uncertain=conf is not None and conf < 0.6)

    @staticmethod
    def _add_cuda_dlls():
        import os
        import sys
        if sys.platform != "win32":
            return
        import site
        roots = list(site.getsitepackages()) + [site.getusersitepackages()]
        for root in roots:
            base = os.path.join(root, "nvidia")
            if not os.path.isdir(base):
                continue
            for pkg in os.listdir(base):
                bin_dir = os.path.join(base, pkg, "bin")
                if os.path.isdir(bin_dir):
                    try:
                        os.add_dll_directory(bin_dir)
                    except OSError:
                        pass
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    def _load_whisper(self):
        if self._whisper is not None:
            return self._whisper
        lock = getattr(self, "_model_lock", None)
        if lock is None:
            return self._load_whisper_now()
        with lock:
            if self._whisper is not None:
                return self._whisper
            return self._load_whisper_now()

    def _load_whisper_now(self):
        self._add_cuda_dlls()
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise SpeechUnavailable("faster-whisper is not installed: pip install faster-whisper") from e
        attempts = []
        if self.device in ("auto", "cuda"):
            attempts.append(("cuda", "float16", self.whisper_model_name or "small.en"))
        if self.device in ("auto", "cpu"):
            attempts.append(("cpu", "int8", self.whisper_model_name or "base.en"))
        errors = []
        for device, compute, name in attempts:
            try:
                self._whisper = WhisperModel(name, device=device, compute_type=compute)
                self.notes.append(f"Whisper '{name}' loaded on {device} ({compute})")
                return self._whisper
            except Exception as e:
                errors.append(f"{device}: {e}")
        raise SpeechUnavailable("could not load Whisper: " + " | ".join(errors))

    def _recognize_whisper(self, audio):
        import numpy as np
        model = self._load_whisper()
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = model.transcribe(
            samples, language="en", beam_size=5, vad_filter=True, temperature=0.0,
            condition_on_previous_text=False, initial_prompt=COMMAND_PROMPT,
        )
        segments = list(segments)
        if not segments:
            return None
        text = " ".join(s.text.strip() for s in segments).strip()
        no_speech = max(s.no_speech_prob for s in segments)
        logprob = sum(s.avg_logprob for s in segments) / len(segments)
        if no_speech > 0.6 or not text or looks_like_prompt_echo(text):
            return None
        conf = round(float(np.exp(logprob)), 3)
        return Transcript(text=text, engine="whisper", confidence=conf, uncertain=logprob < -0.8)

    def _load_vosk(self):
        if self._vosk is not None:
            return self._vosk
        try:
            import vosk
        except ImportError as e:
            raise SpeechUnavailable("vosk is not installed: pip install vosk") from e
        if not self.vosk_model_path:
            raise SpeechUnavailable("download a Vosk model (e.g. vosk-model-en-in-0.5) and pass --vosk-model PATH")
        vosk.SetLogLevel(-1)
        self._vosk = vosk.Model(self.vosk_model_path)
        return self._vosk

    def _recognize_vosk(self, audio):
        import json
        import vosk
        model = self._load_vosk()
        rec = vosk.KaldiRecognizer(model, 16000)
        rec.SetMaxAlternatives(3)
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        result = json.loads(rec.FinalResult())
        alts = [a for a in result.get("alternatives", []) if a.get("text")]
        if not alts:
            return None
        return Transcript(text=alts[0]["text"], alternatives=[a["text"] for a in alts[1:]], engine="vosk",
                          confidence=alts[0].get("confidence"))


SPOKEN = [
    (re.compile(r"https?://(?:www\.)?([^/\s]+)\S*"), r"\1"),
    (re.compile(r"\bvscode\b", re.I), "V S Code"),
    (re.compile(r"\bctrl\b", re.I), "control"),
    (re.compile(r"\bIR\b"), "I R"),
    (re.compile(r"\.txt\b"), " dot T X T"),
    (re.compile(r"\.py\b"), " dot P Y"),
    (re.compile(r"\.pdf\b"), " dot P D F"),
    (re.compile(r"\.docx?\b"), " dot doc"),
    (re.compile(r"\s\*\s"), " times "),
    (re.compile(r"\s/\s"), " divided by "),
    (re.compile(r"\s\+\s"), " plus "),
    (re.compile(r"\s-\s"), " minus "),
    (re.compile(r"\bWould\b"), "I would"),
    (re.compile(r"[\(\)\[\]{}'\"]"), ""),
]


def spoken_form(text, limit=150):
    out = re.sub(r"\s*\([^)]*\)", "", text)
    for pattern, repl in SPOKEN:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > limit:
        cut = re.split(r"(?<=[.!?])\s", out)
        out = cut[0] if len(cut[0]) <= limit else out[:limit].rsplit(" ", 1)[0]
        out += ". The details are on screen."
    return out


class Speaker:
    def __init__(self, enabled=True, rate=180):
        self.enabled = enabled
        self.rate = rate
        self.last = None
        self.last_time = 0.0
        self.latencies = []
        self._queue = queue.Queue()
        self._engine = None
        self._busy = threading.Event()
        self.last_active = 0.0
        self._stop_now = threading.Event()
        self._sapi = None
        self.ready = threading.Event()
        self.error = None
        self._thread = None
        if enabled:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _open_sapi(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Rate = max(-10, min(10, round((self.rate - 180) / 20)))
        for token in voice.GetVoices():
            desc = token.GetDescription()
            if "India" in desc or "Heera" in desc or "Ravi" in desc:
                voice.Voice = token
                break
        return voice

    def _worker(self):
        import sys
        sapi = None
        if sys.platform == "win32":
            try:
                sapi = self._open_sapi()
            except Exception as e:
                self.error = f"Windows voice unavailable ({type(e).__name__}: {e}). Run: py -3.12 -m pip install pywin32"
        if sapi is None:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", self.rate)
                self.error = None
            except Exception as e:
                self._engine = None
                self.error = self.error or f"voice output unavailable ({type(e).__name__}: {e}). Run: py -3.12 -m pip install pyttsx3"
        self._sapi = sapi
        self.ready.set()
        while True:
            text, queued_at = self._queue.get()
            if text is None:
                return
            if sapi is None and self._engine is None:
                continue
            self._busy.set()
            self.last_active = time.time()
            self._stop_now.clear()
            try:
                self.latencies.append(round((time.perf_counter() - queued_at) * 1000))
                if sapi is not None:
                    sapi.Speak(text, 1)
                    while not sapi.WaitUntilDone(80):
                        if self._stop_now.is_set():
                            sapi.Speak("", 3)
                            break
                else:
                    self._engine.say(text)
                    self._engine.runAndWait()
            except Exception as e:
                self.error = f"voice output failed ({type(e).__name__}: {e})"
            finally:
                self.last_active = time.time()
                self._busy.clear()

    def say(self, text, show=True):
        if not text:
            return
        if show:
            print(f"  >> {text}")
        if not self.enabled:
            return
        spoken = spoken_form(text)
        now = time.time()
        if spoken == self.last and now - self.last_time < 8:
            return
        self.last, self.last_time = spoken, now
        self._queue.put((spoken, time.perf_counter()))

    def stop(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._stop_now.set()
        if self._engine is not None and self._busy.is_set():
            try:
                self._engine.stop()
            except Exception:
                pass

    def wait(self, timeout=12):
        deadline = time.time() + timeout
        while (not self._queue.empty() or self._busy.is_set()) and time.time() < deadline:
            time.sleep(0.05)

    @property
    def speaking(self):
        return self._busy.is_set() or not self._queue.empty()
