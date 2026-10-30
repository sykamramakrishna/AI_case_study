import ast
import math
import operator
import re

from .lexer import NUMBER_WORDS

LEADING = re.compile(r"^\s*(what\s+is|what's|whats|how\s+much\s+is|calculate|compute|evaluate|tell\s+me)\s+", re.I)
WORD_OPS = [
    (r"\bsquare\s+root\s+of\s+([\d.]+)", r"sqrt(\1)"),
    (r"([\d.]+)\s*(?:%|percent|per\s+cent)\s+of\b", r"(\1/100)*"),
    (r"([\d.]+)\s*(?:%|percent|per\s+cent)", r"(\1/100)"),
    (r"\bmultiplied\s+by\b", "*"),
    (r"\btimes\b", "*"),
    (r"\binto\b", "*"),
    (r"(?<=\d)\s*x\s*(?=\d)", "*"),
    (r"\bdivided\s+by\b", "/"),
    (r"\bover\b", "/"),
    (r"\bplus\b", "+"),
    (r"\badded\s+to\b", "+"),
    (r"\bminus\b", "-"),
    (r"\bless\b", "-"),
    (r"\bto\s+the\s+power\s+of\b", "**"),
    (r"\bpower\b", "**"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
    (r"\bmod(?:ulo)?\b", "%"),
    (r"\^", "**"),
    (r"[×✕]", "*"),
    (r"÷", "/"),
]
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Mod: operator.mod, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FUNCS = {"sqrt": math.sqrt}


class CalcError(ValueError):
    pass


SMALL = {k: v for k, v in NUMBER_WORDS.items() if v < 100}
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "million": 1000000,
          "crore": 10000000, "crores": 10000000}


def words_to_numbers(text):
    tokens = re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?|[^A-Za-z\d]+", text)
    out, total, current, active = [], 0, 0, False

    def flush():
        nonlocal total, current, active
        if active:
            out.append(str(total + current))
        total, current, active = 0, 0, False

    for tok in tokens:
        low = tok.lower()
        if low in SMALL:
            current += SMALL[low]
            active = True
        elif low in SCALES and active:
            if SCALES[low] == 100:
                current *= 100
            else:
                total += current * SCALES[low]
                current = 0
        elif tok.isdigit() and not active:
            current, active = int(tok), True
        elif low == "and" and active:
            continue
        elif not tok.strip() and active:
            continue
        else:
            flush()
            out.append(tok if not out or not out[-1][-1:].isdigit() or not tok[:1].isalnum() else " " + tok)
    flush()
    return re.sub(r"(\d)([A-Za-z])", r"\1 \2", "".join(out))


def to_expression(text):
    expr = LEADING.sub("", text.strip().rstrip("?.! "))
    expr = words_to_numbers(expr)
    expr = expr.replace(",", "")
    for pattern, repl in WORD_OPS:
        expr = re.sub(pattern, repl, expr, flags=re.I)
    expr = re.sub(r"\s+", " ", expr).strip()
    if not re.fullmatch(r"[\d.\s+\-*/%()sqrt]+", expr) or not re.search(r"\d", expr):
        raise CalcError(f"I can only calculate arithmetic, not '{text}'")
    return expr


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise CalcError("exponent too large")
        return BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and len(node.args) == 1:
        return FUNCS[node.func.id](_eval(node.args[0]))
    raise CalcError("unsupported expression")


def calculate(text):
    expr = to_expression(text)
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        raise CalcError("division by zero")
    except (SyntaxError, TypeError, ValueError) as e:
        raise CalcError(f"could not understand the expression '{expr}'") from e
    if abs(value) > 1e15:
        raise CalcError("result too large")
    expr = re.sub(r"\s*(\*\*|[+\-*/%])\s*", r" \1 ", expr.replace(" ", "")).replace("( ", "(").strip()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 6)
    return expr, value
