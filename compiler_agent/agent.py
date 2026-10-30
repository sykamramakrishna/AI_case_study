import copy
from dataclasses import dataclass, field
from typing import Any, List

from .ast_nodes import pretty
from .executor import ExecutionError, Executor
from .ir_generator import format_ir, generate_ir
from .lexer import Lexer, LexerError
from .optimizer import optimize_ast, optimize_ir
from .parser import Parser, ParserError
from .semantic_analyzer import SemanticAnalyzer, SemanticError


class CompilationError(Exception):
    pass


@dataclass
class CompileResult:
    command: str
    tokens: List[Any] = field(default_factory=list)
    ast: Any = None
    semantic_ast: Any = None
    ir: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    optimizations: List[str] = field(default_factory=list)


def _section(title, body):
    print(f"\n--- {title} " + "-" * max(0, 60 - len(title)))
    print(body)


class Agent:
    def __init__(self, dry_run: bool = True, optimize: bool = True, confirm=None, backend=None, echo=True, policy=None):
        self.analyzer = SemanticAnalyzer(policy=policy)
        self.executor = Executor(dry_run=dry_run, confirm=confirm, backend=backend, echo=echo, policy=policy)
        self.optimize = optimize
        self.session_clipboard = None
        self.last = None

    def compile(self, command: str, verbose: bool = False) -> list:
        result = CompileResult(command=command)
        try:
            result.tokens = Lexer(command).tokenize()
            if verbose:
                _section("1. LEXER (tokens)", result.tokens)
            program = Parser(result.tokens).parse()
            if verbose:
                _section("2. PARSER (abstract syntax tree)", pretty(program))
            program = self.analyzer.analyze(program, initial_clipboard=self.session_clipboard)
            result.warnings = list(self.analyzer.warnings)
            result.semantic_ast = copy.deepcopy(program)
            if verbose:
                body = "OK" + "".join(f"\n  warning: {w}" for w in result.warnings)
                _section("3. SEMANTIC ANALYSIS", body + "\n" + pretty(program))
            if self.optimize:
                program, report = optimize_ast(program)
                result.optimizations.extend(report)
            ir = generate_ir(program)
            if self.optimize:
                ir, report = optimize_ir(ir)
                result.optimizations.extend(report)
            result.ast = program
            result.ir = ir
            if verbose:
                if self.optimize:
                    _section("4. OPTIMIZER", "\n".join(result.optimizations) or "nothing to optimize")
                _section("5. INTERMEDIATE REPRESENTATION", format_ir(ir))
            self.last = result
            return ir
        except (LexerError, ParserError, SemanticError) as e:
            raise CompilationError(f'"{command}" -> {type(e).__name__}: {e}') from e

    def run_ir(self, ir: list) -> list:
        clipboard_after = self.analyzer.final_state.clipboard
        results = self.executor.run(ir)
        if clipboard_after is not None:
            self.session_clipboard = clipboard_after
        return results

    def run(self, command: str, verbose: bool = False) -> list:
        ir = self.compile(command, verbose=verbose)
        if verbose:
            _section("6. EXECUTION", "")
        return self.run_ir(ir)


__all__ = ["Agent", "CompilationError", "CompileResult", "ExecutionError"]
