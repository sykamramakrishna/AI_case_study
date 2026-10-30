import time

from .agent import Agent, CompilationError
from .ast_nodes import ActionNode, IfNode, ProgramNode, RepeatNode, _label
from .executor import ExecutionError, describe
from .lexer import Lexer, LexerError
from .parser import Parser, ParserError
from .semantic_analyzer import SemanticError


def ast_to_json(node):
    if isinstance(node, ProgramNode):
        return {"kind": "program", "label": "Program", "children": [ast_to_json(s) for s in node.statements]}
    if isinstance(node, ActionNode):
        return {"kind": "action", "label": _label(node), "verb": node.verb, "children": []}
    if isinstance(node, IfNode):
        children = [{"kind": "branch", "label": "then", "children": [ast_to_json(s) for s in node.then_body]}]
        if node.else_body:
            children.append({"kind": "branch", "label": "else", "children": [ast_to_json(s) for s in node.else_body]})
        return {"kind": "if", "label": _label(node), "children": children}
    if isinstance(node, RepeatNode):
        return {"kind": "repeat", "label": _label(node), "children": [ast_to_json(s) for s in node.body]}
    return {"kind": "other", "label": str(node), "children": []}


def tokens_to_json(tokens):
    return [{"type": t.type.name, "value": t.value if not isinstance(t.value, str) else t.value, "text": t.text}
            for t in tokens if t.type.name != "EOF"]


def stage_of(error):
    if isinstance(error, LexerError):
        return "lexer"
    if isinstance(error, ParserError):
        return "parser"
    if isinstance(error, SemanticError):
        return "semantic"
    return "execute"


def compile_report(agent, command, execute=True):
    report = {"command": command, "ok": True, "stages": {}, "error": None, "results": [], "confirms": []}
    started = time.perf_counter()
    try:
        tokens = Lexer(command).tokenize()
        report["stages"]["lexer"] = tokens_to_json(tokens)
        raw_ast = Parser(tokens).parse()
        report["stages"]["parser"] = ast_to_json(raw_ast)
        ir = agent.compile(command)
        result = agent.last
        report["stages"]["semantic"] = {"warnings": result.warnings, "ast": ast_to_json(result.semantic_ast)}
        report["stages"]["optimizer"] = result.optimizations
        report["stages"]["ir"] = ir
        report["confirms"] = [describe(op) for op in ir if op["args"].get("destructive")]
        if execute:
            report["results"] = agent.run_ir(ir)
    except (LexerError, ParserError, CompilationError) as e:
        cause = e.__cause__ or e
        report["ok"] = False
        report["error"] = {"stage": stage_of(cause), "message": str(cause)}
    except ExecutionError as e:
        report["ok"] = False
        report["error"] = {"stage": "execute", "message": str(e)}
    report["ms"] = round((time.perf_counter() - started) * 1000, 1)
    return report


def make_agent(dry_run=True, confirm=None):
    agent = Agent(dry_run=dry_run, confirm=confirm, echo=False)
    return agent
