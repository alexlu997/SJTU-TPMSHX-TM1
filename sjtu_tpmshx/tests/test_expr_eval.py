"""User expressions preserve finite results and reject oversized integer powers."""
import subprocess
import sys

import pytest

from sjtu_tpmshx.ui.expr_eval import eval_expr


@pytest.mark.parametrize('text,expected', [
    ('0.042 / 2', .021),
    ('2^3', 8.),
    ('2**-3', .125),
    ('(-2)^3', -8.),
    ('0^(10^1000)', 0.),
    ('1^(10^1000)', 1.),
    ('(-1)^(10^1000 + 1)', -1.),
    ('atan(1) * 180 / pi', 45.),
    ('round(max(1.1, 2.25), 1)', 2.2),
])
def test_supported_expression(text, expected):
    assert eval_expr(text) == pytest.approx(expected)


@pytest.mark.parametrize('text', [
    '1 / 0', 'sqrt(-1)', '(-1)^0.5', 'inf + 1', '1e308 * 10',
    '().__class__', '__import__("os")', '"value"',
])
def test_invalid_expression_returns_failure(text):
    assert eval_expr(text) is None


def test_deep_expression_returns_parse_failure():
    # Fits a QLineEdit, but exceeds the parser's recursion limit.
    assert eval_expr('1+' * 15_000 + '1') is None


def test_large_power_returns_without_unbounded_integer_work():
    subprocess.run(
        [sys.executable, '-c',
         'from sjtu_tpmshx.ui.expr_eval import eval_expr; '
         'assert eval_expr("9**9**9") is None'],
        check=True, capture_output=True, text=True, timeout=5,
    )
