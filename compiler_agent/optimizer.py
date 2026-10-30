import copy

from .ast_nodes import ActionNode, IfNode, ProgramNode, RepeatNode

UNROLL_LIMIT = 8
FOCUS_CHANGERS = {"OPEN_URL", "OPEN_FILE", "SEARCH", "CLICK", "CLOSE_APP"}
JUMP_OPS = {"JUMP", "JUMP_IF_FALSE", "LOOP_NEXT"}


def optimize_ast(program: ProgramNode, unroll_limit=UNROLL_LIMIT):
    report = []
    program.statements = _optimize_block(program.statements, report, unroll_limit)
    return program, report


def _optimize_block(statements, report, limit):
    out = []
    for stmt in statements:
        if isinstance(stmt, IfNode):
            stmt.then_body = _optimize_block(stmt.then_body, report, limit)
            stmt.else_body = _optimize_block(stmt.else_body, report, limit)
            static = stmt.condition.static
            if static is not None:
                kept = stmt.then_body if static else stmt.else_body
                report.append(
                    f"Constant folding: {stmt.condition.describe()} is always {static} here; "
                    f"removed the {'else' if static else 'then'} branch"
                )
                out.extend(kept)
                continue
            out.append(stmt)
        elif isinstance(stmt, RepeatNode):
            stmt.body = _optimize_block(stmt.body, report, limit)
            flat = all(isinstance(s, ActionNode) for s in stmt.body)
            if flat and stmt.count * len(stmt.body) <= limit:
                report.append(f"Loop unrolling: repeat x{stmt.count} expanded into {stmt.count * len(stmt.body)} straight-line steps")
                for _ in range(stmt.count):
                    out.extend(copy.deepcopy(s) for s in stmt.body)
                continue
            out.append(stmt)
        else:
            out.append(stmt)
    return out


def optimize_ir(ir):
    report = []
    changed = True
    while changed:
        changed = False
        for rule in (_redundant_focus, _merge_waits, _unreachable, _jump_to_next, _unused_labels):
            ir, messages = rule(ir)
            if messages:
                changed = True
                report.extend(messages)
    return ir, report


def _redundant_focus(ir):
    out, messages, focused = [], [], None
    for op in ir:
        name = op["op"]
        if name == "LABEL" or name in FOCUS_CHANGERS:
            focused = None
        elif name == "OPEN_APP":
            app = op["args"].get("app")
            if app is not None and out and out[-1]["op"] == "OPEN_APP" and out[-1]["args"].get("app") == app:
                messages.append(f"Peephole: removed duplicate OPEN_APP {app!r}")
                continue
            focused = app
        elif name == "SWITCH_APP":
            app = op["args"].get("app")
            if app is not None and app == focused:
                messages.append(f"Peephole: removed redundant SWITCH_APP {app!r} (already in front)")
                continue
            focused = app
        out.append(op)
    return out, messages


def _merge_waits(ir):
    out, messages = [], []
    for op in ir:
        if op["op"] == "WAIT" and out and out[-1]["op"] == "WAIT":
            prev = out[-1]
            total = prev["args"]["seconds"] + op["args"]["seconds"]
            out[-1] = {"op": "WAIT", "target": None, "args": {**prev["args"], "seconds": total}}
            messages.append(f"Peephole: merged consecutive WAITs into one {total}s wait")
            continue
        out.append(op)
    return out, messages


def _unreachable(ir):
    out, messages, dead = [], [], False
    for op in ir:
        if op["op"] == "LABEL":
            dead = False
        elif dead:
            messages.append(f"Dead code: removed unreachable {op['op']}")
            continue
        out.append(op)
        if op["op"] == "JUMP":
            dead = True
    return out, messages


def _jump_to_next(ir):
    out, messages = [], []
    for i, op in enumerate(ir):
        if op["op"] == "JUMP":
            j = i + 1
            following = set()
            while j < len(ir) and ir[j]["op"] == "LABEL":
                following.add(ir[j]["args"]["name"])
                j += 1
            if op["args"]["label"] in following:
                messages.append("Peephole: removed jump to the next instruction")
                continue
        out.append(op)
    return out, messages


def _unused_labels(ir):
    used = {op["args"]["label"] for op in ir if op["op"] in JUMP_OPS}
    out, messages = [], []
    for op in ir:
        if op["op"] == "LABEL" and op["args"]["name"] not in used:
            messages.append(f"Removed unused label {op['args']['name']}")
            continue
        out.append(op)
    return out, messages
