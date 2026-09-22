"""Safe expression evaluator for LineEdit fields.

Users type `0.042 / 2`, `2 * pi * 0.01`, `atan(0.5) * 180 / pi`, etc; on
commit the expression is replaced with the computed value. Parsing is
AST-based with an allow-list of node types and function names — no
`eval()` anywhere, no access to globals.
"""
from __future__ import annotations

import ast
import math

# Allowed callable names — all pulled from `math` module.
_ALLOWED_FUNCS = {
    'abs': abs, 'round': round, 'min': min, 'max': max,
    'sqrt': math.sqrt, 'pow': math.pow,
    'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
    'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
    'atan2': math.atan2,
    'sinh': math.sinh, 'cosh': math.cosh, 'tanh': math.tanh,
    'exp': math.exp, 'log': math.log, 'log10': math.log10,
    'radians': math.radians, 'degrees': math.degrees,
    'floor': math.floor, 'ceil': math.ceil,
}
_ALLOWED_CONSTS = {
    'pi': math.pi, 'e': math.e, 'tau': math.tau, 'inf': math.inf,
}

# AST node types we accept — binary ops, unary ops, literals, names, calls.
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Call, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.USub, ast.UAdd,
)


def is_expression(text):
    """Heuristic: text looks like a formula (contains an operator) rather
    than a plain number. Cheap to call on every editingFinished."""
    if text is None:
        return False
    s = text.strip()
    if not s:
        return False
    try:
        float(s)
        return False  # plain number
    except ValueError:
        pass
    return any(op in s for op in ('+', '-', '*', '/', '(', ')', '%', '^')) \
        or any(fn + '(' in s for fn in _ALLOWED_FUNCS)


def eval_expr(text):
    """Parse + evaluate `text` with the safe AST walker.

    Returns float on success, None on any parse/eval failure. No
    exception leaks — callers check `None` and leave the original
    field text alone.
    """
    if text is None:
        return None
    s = str(text).strip().replace('^', '**')  # Excel-style exponent
    if not s:
        return None
    try:
        tree = ast.parse(s, mode='eval')
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return None
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return None
            if node.func.id not in _ALLOWED_FUNCS:
                return None
        if isinstance(node, ast.Name):
            if (node.id not in _ALLOWED_CONSTS
                    and node.id not in _ALLOWED_FUNCS):
                return None
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                return None

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in _ALLOWED_CONSTS:
                return _ALLOWED_CONSTS[n.id]
            return _ALLOWED_FUNCS[n.id]
        if isinstance(n, ast.UnaryOp):
            v = _eval(n.operand)
            return +v if isinstance(n.op, ast.UAdd) else -v
        if isinstance(n, ast.BinOp):
            a = _eval(n.left); b = _eval(n.right)
            op = n.op
            if isinstance(op, ast.Add):      return a + b
            if isinstance(op, ast.Sub):      return a - b
            if isinstance(op, ast.Mult):     return a * b
            if isinstance(op, ast.Div):      return a / b
            if isinstance(op, ast.Mod):      return a % b
            if isinstance(op, ast.Pow):      return a ** b
            if isinstance(op, ast.FloorDiv): return a // b
            raise ValueError("unsupported op")
        if isinstance(n, ast.Call):
            fn = _eval(n.func)
            args = [_eval(a) for a in n.args]
            return fn(*args)
        raise ValueError("unsupported node")

    try:
        result = _eval(tree)
    except Exception:
        return None
    try:
        val = float(result)
    except (TypeError, ValueError):
        return None
    # 2026-05-20 UI sweep: block NaN / ±Inf from leaking into the
    # LineEdit (e.g. user types `1/0`, `0**-1`, or `log(0)`). Without
    # this the field would be silently overwritten with the literal
    # text `inf` / `nan`, which the solver then sees as a parse failure
    # at compute time.
    import math
    if not math.isfinite(val):
        return None
    return val
