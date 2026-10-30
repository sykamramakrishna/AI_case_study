import argparse
import os
import sys

from compiler_agent.ui_api import CompilerApi

HERE = os.path.dirname(os.path.abspath(__file__))


class JsBridge:
    def __init__(self, api):
        self._api = api

    def status(self):
        return self._api.status()

    def process(self, text, source="typed", alternatives=None, uncertain=False):
        return self._api.process(text, source, alternatives or [], bool(uncertain))

    def execute(self, approved=True):
        return self._api.execute(bool(approved))

    def listen(self, force=False, fresh=False):
        return self._api.listen(bool(force), bool(fresh))

    def set_wake_mode(self, mode):
        return self._api.set_wake_mode(mode)

    def set_mode(self, mode):
        return self._api.set_mode(mode)

    def set_speak(self, on):
        return self._api.set_speak(on)

    def stop(self):
        return self._api.stop()

    def greet(self):
        return self._api.greet()

    def memory_summary(self):
        return self._api.memory_summary()


def build_parser():
    p = argparse.ArgumentParser(description="Compiler desktop app")
    p.add_argument("--live", action="store_true", help="start in live mode (you can also switch in the app)")
    p.add_argument("--llm", action="store_true", help="use the free local AI model through Ollama")
    p.add_argument("--model", default=None, help="Ollama model (default qwen3:8b)")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    p.add_argument("--engine", choices=["auto", "google", "whisper", "vosk"], default="auto")
    p.add_argument("--whisper-model")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p.add_argument("--vosk-model")
    p.add_argument("--language", default="en-IN")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-speak", action="store_true", help="start with spoken replies off")
    p.add_argument("--always-listen", action="store_true", help="treat everything you say as a command (no wake word)")
    p.add_argument("--debug", action="store_true", help="open the web inspector")
    return p


def make_api(args):
    llm = None
    if args.llm:
        from compiler_agent.llm import OllamaClient, pick_model
        llm = OllamaClient(model=pick_model(args.model, args.ollama_host), host=args.ollama_host)
        llm.warm_up_async()
    memory = None
    if not args.no_memory:
        from compiler_agent.memory_store import Memory
        memory = Memory()
    return CompilerApi(dry_run=not args.live, llm=llm, memory=memory, speak=not args.no_speak,
                    engine=args.engine, language=args.language, whisper_model=args.whisper_model,
                    device=args.device, vosk_model=args.vosk_model,
                    wake_mode="always" if args.always_listen else "wake")


def install_stop_hotkey(api):
    try:
        from pynput import keyboard
    except ImportError:
        return
    listener = keyboard.GlobalHotKeys({"<ctrl>+<alt>+s": api.stop})
    listener.daemon = True
    listener.start()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        import webview
    except ImportError:
        print("The desktop app needs pywebview:  py -3.12 -m pip install pywebview")
        return 1
    api = make_api(args)
    install_stop_hotkey(api)
    page = os.path.join(HERE, "ui", "index.html")
    webview.create_window("Compiler Voice Assistant", url=page, js_api=JsBridge(api), width=1440, height=900,
                          min_size=(960, 640), background_color="#091013")
    webview.start(debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
