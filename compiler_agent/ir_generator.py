from .ast_nodes import ActionNode, IfNode, ProgramNode, RepeatNode

FOCUS_BEFORE = {"PASTE", "TYPE_TEXT"}
CONTROL_OPS = {"LABEL", "JUMP", "JUMP_IF_FALSE", "TEST", "LOOP_INIT", "LOOP_NEXT"}


class IRGenerator:
    def __init__(self):
        self.code = []
        self.label_count = 0
        self.reg_count = 0

    def new_label(self):
        self.label_count += 1
        return f"L{self.label_count}"

    def emit(self, op, target=None, **args):
        self.code.append({"op": op, "target": target, "args": args})

    def generate(self, program: ProgramNode):
        for stmt in program.statements:
            self.statement(stmt)
        return self.code

    def statement(self, stmt):
        if isinstance(stmt, ActionNode):
            self.action(stmt)
        elif isinstance(stmt, IfNode):
            self.if_statement(stmt)
        elif isinstance(stmt, RepeatNode):
            self.repeat(stmt)

    def action(self, action):
        if action.verb == "NEW_DOCUMENT":
            self.new_document(action)
            return
        if action.verb in FOCUS_BEFORE and action.args.get("app"):
            self.emit("SWITCH_APP", action.args["app"], app=action.args["app"])
        self.code.append({"op": action.verb, "target": action.target, "args": dict(action.args)})

    def new_document(self, action):
        app = action.args["app"]
        self.emit("OPEN_APP", app, app=app, new=True)
        self.emit("WAIT", seconds=3)
        if action.args.get("title"):
            self.emit("TYPE_TEXT", None, text=action.args["title"])
            self.emit("PRESS", "enter", keys=["enter"])
        if action.args.get("name"):
            self.emit("SAVE_FILE", action.args["name"])

    def if_statement(self, node):
        cond = node.condition
        else_label = self.new_label()
        extra = {"app": cond.app} if cond.app else {}
        self.emit("TEST", cond.subject, kind=cond.kind, negated=cond.negated, **extra)
        self.emit("JUMP_IF_FALSE", label=else_label)
        for stmt in node.then_body:
            self.statement(stmt)
        if node.else_body:
            end_label = self.new_label()
            self.emit("JUMP", label=end_label)
            self.emit("LABEL", name=else_label)
            for stmt in node.else_body:
                self.statement(stmt)
            self.emit("LABEL", name=end_label)
        else:
            self.emit("LABEL", name=else_label)

    def repeat(self, node):
        reg = f"r{self.reg_count}"
        self.reg_count += 1
        start = self.new_label()
        self.emit("LOOP_INIT", reg=reg, count=node.count)
        self.emit("LABEL", name=start)
        for stmt in node.body:
            self.statement(stmt)
        self.emit("LOOP_NEXT", reg=reg, label=start)


def generate_ir(program: ProgramNode) -> list:
    return IRGenerator().generate(program)


def format_ir(ir):
    lines = []
    for i, op in enumerate(ir):
        args = dict(op["args"])
        if op["op"] == "LABEL":
            lines.append(f"{args['name']}:")
            continue
        parts = []
        if op.get("target") is not None:
            parts.append(repr(op["target"]))
        if args.get("app") == op.get("target"):
            args.pop("app", None)
        parts.extend(f"{k}={v!r}" for k, v in args.items())
        lines.append(f"  {i:>3}  {op['op']:<14} {' '.join(parts)}".rstrip())
    return "\n".join(lines)
