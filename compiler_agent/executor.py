import os
import threading
import time
from datetime import datetime

from .backends import BackendError, DryRunBackend, LiveBackend

MAX_STEPS = 10000


class ExecutionError(Exception):
    def __init__(self, message, done=None):
        super().__init__(message)
        self.done = done or []


class ExecutionCancelled(ExecutionError):
    pass


def describe(op):
    target = op.get("target")
    names = {
        "DELETE_FILE": f"delete the file '{target}'",
        "CLOSE_APP": f"close {target} (unsaved work may be lost)",
        "RUN_SCRIPT": f"run the Python script '{target}' (it can change files on this computer)",
        "RUN_TESTS": "run the test suite in this folder",
        "WRITE_FILE": f"write the file '{target}' (an existing file with that name is replaced)",
        "CHAT": f"send “{op['args'].get('message', '')}” to {target} on WhatsApp",
    }
    return names.get(op["op"], f"{op['op'].lower()} {target or ''}".strip())


class Executor:
    def __init__(self, dry_run: bool = True, screenshot_dir: str = "./screenshots",
                 backend=None, confirm=None, echo=True, policy=None):
        from .policy import DEFAULT_POLICY
        self.policy = policy or DEFAULT_POLICY
        self.cancel_event = threading.Event()
        self.dry_run = dry_run
        self.screenshot_dir = screenshot_dir
        self.confirm = confirm
        self.echo = echo
        self.log = []
        if backend is not None:
            self.backend = backend
        elif dry_run:
            self.backend = DryRunBackend(screenshot_dir)
        else:
            try:
                self.backend = LiveBackend(screenshot_dir)
            except BackendError as e:
                raise ExecutionError(str(e)) from e
            os.makedirs(self.screenshot_dir, exist_ok=True)

    def _say(self, msg: str) -> str:
        if self.echo:
            print(f"{self.backend.tag} {msg}")
        return msg

    def run(self, ir: list) -> list:
        labels = {op["args"]["name"]: i for i, op in enumerate(ir) if op["op"] == "LABEL"}
        results = []
        registers = {}
        flag = False
        pc = 0
        steps = 0
        self.cancel_event.clear()
        while pc < len(ir):
            if self.cancel_event.is_set():
                raise ExecutionCancelled(f"Stopped by you after {len(results)} step(s)", done=list(results))
            steps += 1
            if steps > MAX_STEPS:
                raise ExecutionError("Stopped: program ran for too many steps")
            op = ir[pc]
            name = op["op"]
            args = op["args"]
            if name == "LABEL":
                pc += 1
                continue
            if name == "JUMP":
                pc = self._jump(labels, args["label"])
                continue
            if name == "JUMP_IF_FALSE":
                pc = pc + 1 if flag else self._jump(labels, args["label"])
                continue
            if name == "LOOP_INIT":
                registers[args["reg"]] = args["count"]
                pc += 1
                continue
            if name == "LOOP_NEXT":
                registers[args["reg"]] -= 1
                pc = self._jump(labels, args["label"]) if registers[args["reg"]] > 0 else pc + 1
                continue
            if name == "TEST":
                flag = self._test(op)
                pc += 1
                continue
            handler = getattr(self, f"_op_{name.lower()}", None)
            if handler is None:
                raise ExecutionError(f"No executor implemented for op '{name}'")
            if args.get("destructive") and self.confirm is not None and not self.confirm(describe(op)):
                result = self._say(f"Skipped: {describe(op)} (not confirmed)")
            else:
                try:
                    result = handler(op)
                except ExecutionError:
                    raise
                except BackendError as e:
                    raise ExecutionError(f"{name} failed: {e}", done=list(results)) from e
                except Exception as e:
                    raise ExecutionError(f"{name} failed: {type(e).__name__}: {e}", done=list(results)) from e
            self.log.append({
                "op": name,
                "target": op.get("target"),
                "result": result,
                "time": datetime.now().isoformat(timespec="seconds"),
            })
            results.append(result)
            pc += 1
        return results

    @staticmethod
    def _jump(labels, label):
        if label not in labels:
            raise ExecutionError(f"Jump to undefined label {label}")
        return labels[label]

    def _test(self, op):
        args = op["args"]
        if args["kind"] == "EXISTS":
            value = self.backend.file_exists(op["target"])
            what = "exists"
        else:
            value = self.backend.is_running(args.get("app") or op["target"])
            what = "is running"
        outcome = value != args.get("negated", False)
        self._say(f"Check: '{op['target']}' {what} -> {value}{' (negated)' if args.get('negated') else ''}")
        return outcome

    def _op_open_app(self, op):
        return self._say(self.backend.open_app(op["args"].get("app") or op["target"], new=op["args"].get("new", False)))

    def _op_play(self, op):
        return self._say(self.backend.play_youtube(op["args"]["query"]))

    def _op_open_url(self, op):
        return self._say(self.backend.open_url(op["args"]["url"]))

    def _op_open_file(self, op):
        return self._say(self.backend.open_file(op["target"]))

    def _op_close_app(self, op):
        return self._say(self.backend.close_app(op["args"].get("app") or op["target"]))

    def _op_switch_app(self, op):
        return self._say(self.backend.focus_app(op["args"].get("app") or op["target"]))

    def _op_screenshot(self, op):
        filename = os.path.join(self.screenshot_dir, f"screenshot_{int(time.time() * 1000)}.png")
        return self._say(self.backend.screenshot(filename))

    def _op_type_text(self, op):
        return self._say(self.backend.type_text(op["args"].get("text", "")))

    def _op_search(self, op):
        return self._say(self.backend.search(op["args"]["text"], op["args"].get("site")))

    def cancel(self):
        self.cancel_event.set()

    def _op_write_file(self, op):
        return self._say(self.backend.write_file(op["target"], op["args"]["text"]))

    def _op_chat(self, op):
        return self._say(self.backend.whatsapp_chat(op["target"], op["args"].get("message"), op["args"].get("phone")))

    def _op_append_file(self, op):
        return self._say(self.backend.append_file(op["target"], op["args"]["text"]))

    def _op_run_script(self, op):
        return self._say(self.backend.run_script(op["target"], self.policy.script_timeout, self.policy.max_output_chars))

    def _op_run_tests(self, op):
        return self._say(self.backend.run_tests(op["target"], self.policy.test_timeout, self.policy.max_output_chars))

    def _op_create_folder(self, op):
        return self._say(self.backend.create_folder(op["target"]))

    def _op_minimize(self, op):
        return self._say(self.backend.window("minimize"))

    def _op_maximize(self, op):
        return self._say(self.backend.window("maximize"))

    def _op_lock(self, op):
        return self._say(self.backend.lock())

    def _op_tell(self, op):
        now = datetime.now()
        if op["target"] == "time":
            return self._say(f"It's {now.strftime('%I:%M %p').lstrip('0')}")
        return self._say(f"Today is {now.strftime('%A, %d %B %Y')}")

    def _op_calculate(self, op):
        return self._say(f"{op['args']['expr']} = {op['args']['value']}")

    def _op_press(self, op):
        return self._say(self.backend.press(op["args"]["keys"]))

    def _op_copy(self, op):
        return self._say(self.backend.copy())

    def _op_paste(self, op):
        return self._say(self.backend.paste(op.get("target")))

    def _op_select(self, op):
        return self._say(self.backend.select_all())

    def _op_save_file(self, op):
        return self._say(self.backend.save(op.get("target")))

    def _op_create_file(self, op):
        return self._say(self.backend.create_file(op["target"]))

    def _op_delete_file(self, op):
        return self._say(self.backend.delete_file(op["target"]))

    def _op_wait(self, op):
        return self._say(self.backend.wait(op["args"]["seconds"]))

    def _op_scroll(self, op):
        return self._say(self.backend.scroll(op["target"], op["args"].get("amount", 5)))

    def _op_volume(self, op):
        return self._say(self.backend.volume(op["target"]))

    def _op_click(self, op):
        return self._say(self.backend.click_text(op["args"]["text"]))
