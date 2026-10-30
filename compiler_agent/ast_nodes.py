from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActionNode:
    verb: str
    target: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    word: Optional[str] = field(default=None, compare=False)
    index: int = field(default=0, compare=False)

    def __repr__(self):
        return f"Action({self.verb}, target={self.target!r}, args={self.args})"


@dataclass
class ConditionNode:
    kind: str
    subject: str
    negated: bool = False
    app: Optional[str] = field(default=None, compare=False)
    static: Optional[bool] = field(default=None, compare=False)
    analyzed: bool = field(default=False, compare=False)

    def describe(self):
        verb = "exists" if self.kind == "EXISTS" else "is running"
        return f"{'NOT ' if self.negated else ''}{self.subject!r} {verb}"

    def __repr__(self):
        return f"Cond({self.describe()})"


@dataclass
class IfNode:
    condition: ConditionNode
    then_body: List[Any] = field(default_factory=list)
    else_body: List[Any] = field(default_factory=list)

    def __repr__(self):
        return f"If({self.condition!r}, then={self.then_body}, else={self.else_body})"


@dataclass
class RepeatNode:
    count: int
    body: List[Any] = field(default_factory=list)

    def __repr__(self):
        return f"Repeat({self.count}, {self.body})"


@dataclass
class ProgramNode:
    statements: List[Any] = field(default_factory=list)

    @property
    def actions(self):
        return self.statements

    def __repr__(self):
        return f"Program({self.statements})"


def _label(node):
    if isinstance(node, ProgramNode):
        return "Program"
    if isinstance(node, ActionNode):
        parts = [f"Action {node.verb}"]
        if node.target:
            parts.append(f"target={node.target!r}")
        parts.extend(f"{k}={v!r}" for k, v in node.args.items())
        return "  ".join(parts)
    if isinstance(node, IfNode):
        suffix = "" if node.condition.static is None else f"  [statically {node.condition.static}]"
        return f"If {node.condition.describe()}{suffix}"
    if isinstance(node, RepeatNode):
        return f"Repeat x{node.count}"
    return str(node)


def _children(node):
    if isinstance(node, ProgramNode):
        return [(None, s) for s in node.statements]
    if isinstance(node, IfNode):
        out = [("then", node.then_body)]
        if node.else_body:
            out.append(("else", node.else_body))
        return out
    if isinstance(node, RepeatNode):
        return [(None, s) for s in node.body]
    return []


def pretty(node, prefix="", is_last=True, root=True):
    lines = [_label(node)] if root else []
    kids = _children(node)
    for i, (tag, child) in enumerate(kids):
        last = i == len(kids) - 1
        branch = "`-- " if last else "|-- "
        extend = "    " if last else "|   "
        if tag is not None:
            lines.append(prefix + branch + tag)
            for j, stmt in enumerate(child):
                sub_last = j == len(child) - 1
                lines.append(prefix + extend + ("`-- " if sub_last else "|-- ") + _label(stmt))
                lines.extend(pretty(stmt, prefix + extend + ("    " if sub_last else "|   "), sub_last, False))
        else:
            lines.append(prefix + branch + _label(child))
            lines.extend(pretty(child, prefix + extend, last, False))
    return "\n".join(lines) if root else lines
