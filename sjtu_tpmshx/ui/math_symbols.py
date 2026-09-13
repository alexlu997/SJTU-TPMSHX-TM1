"""math_symbols.py — Unicode subscript / superscript / Greek replacements.

Used to render fluid-mechanics symbols in Qt labels (which don't support
LaTeX natively). Maps the underscore-form a project uses in code (D_h,
mu_f, T_inA) to a Unicode-rich form (Dₕ, μ_f, T_inA → T_in,A) suitable
for QLabel.setText().

For matplotlib axis / title / legend strings, prefer mathtext directly
(``r"$D_h$"``) — much cleaner italic + math italic styling. Use this
module for Qt only.

Public API
----------
to_unicode(s) -> str
    Convert underscore + Greek tokens to Unicode glyphs.
greek(name) -> str
    Look up a single Greek symbol by ASCII name (e.g. ``greek('mu') == 'μ'``).
"""
from __future__ import annotations

from typing import Dict

from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)


# ─── Greek alphabet (lower-case + select upper) ────────────────────


_GREEK: Dict[str, str] = {
    'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ',
    'epsilon': 'ε', 'eps': 'ε', 'zeta': 'ζ', 'eta': 'η',
    'theta': 'θ', 'iota': 'ι', 'kappa': 'κ', 'lambda': 'λ',
    'mu': 'μ', 'nu': 'ν', 'xi': 'ξ', 'omicron': 'ο',
    'pi': 'π', 'rho': 'ρ', 'sigma': 'σ', 'tau': 'τ',
    'upsilon': 'υ', 'phi': 'φ', 'chi': 'χ', 'psi': 'ψ',
    'omega': 'ω',
    'Delta': 'Δ', 'Sigma': 'Σ', 'Pi': 'Π',
    'Lambda': 'Λ', 'Omega': 'Ω', 'Phi': 'Φ',
}


# ─── Unicode subscript / superscript glyph maps ────────────────────


_SUBSCRIPT: Dict[str, str] = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    'a': 'ₐ', 'e': 'ₑ', 'h': 'ₕ', 'i': 'ᵢ', 'j': 'ⱼ',
    'k': 'ₖ', 'l': 'ₗ', 'm': 'ₘ', 'n': 'ₙ', 'o': 'ₒ',
    'p': 'ₚ', 'r': 'ᵣ', 's': 'ₛ', 't': 'ₜ', 'u': 'ᵤ',
    'v': 'ᵥ', 'x': 'ₓ',
}


# ─── Project-specific shorthand map ────────────────────────────────


# Common heat-exchanger / TPMS symbols the project uses in labels.
# Keys = exact substrings; longest-first replacement preserves nested keys.
# These take precedence over the general "X_y" rule below.
_PROJECT_SYMBOLS: Dict[str, str] = {
    'D_h':   'D' + _SUBSCRIPT['h'],          # Dₕ
    'd_h':   'd' + _SUBSCRIPT['h'],
    'k_s':   'k' + _SUBSCRIPT['s'],
    'k_f':   'k' + _SUBSCRIPT['f'] if 'f' in _SUBSCRIPT else 'k_f',
    'rho_s': 'ρ' + _SUBSCRIPT['s'],          # ρₛ
    'rho_f': 'ρ' + _SUBSCRIPT['f'] if 'f' in _SUBSCRIPT else 'ρ_f',
    'mu_f':  'μ' + _SUBSCRIPT['f'] if 'f' in _SUBSCRIPT else 'μ_f',
    'mu_s':  'μ' + _SUBSCRIPT['s'],
    'm_dot': 'ṁ',
    'eps_f': 'ε' + _SUBSCRIPT['f'] if 'f' in _SUBSCRIPT else 'ε_f',
    'eps_s': 'ε' + _SUBSCRIPT['s'],
    'epsilon_A': 'ε_A',
    'epsilon_B': 'ε_B',
    'L_cell':    'L_cell',                   # left explicit
    't_wall':    't_wall',
    'T_inA':     'T_inA',
    'T_inB':     'T_inB',
    'P_inA':     'P_inA',
    'P_inB':     'P_inB',
    'h_v':       'h_v',
    'A_0':       'A' + _SUBSCRIPT['0'],
    'cF':        'c_F',
    'c_F':       'c_F',
    'Re':        'Re',
    'Pr':        'Pr',
    'Nu':        'Nu',
}


def greek(name: str) -> str:
    """Return the Unicode glyph for a Greek letter name; '' if unknown."""
    return _GREEK.get(name, '')


def to_unicode(s: str) -> str:
    """Convert a plain-ASCII engineering string into a Unicode-rich form
    suitable for Qt QLabel rendering.

    Currently translates only the project's exact symbol shortcuts (D_h,
    rho_s, mu_f, m_dot, etc.). General-purpose ``X_y`` → X with Unicode
    subscript y is intentionally NOT applied because most occurrences in
    the codebase are ambiguous (variable names like ``T_inA`` shouldn't
    become Tᵢₙₐ — the underscore is part of the variable not a math
    subscript).

    For matplotlib labels prefer ``r"$D_h$"`` — this function targets Qt
    where mathtext rendering is unavailable.
    """
    out = s
    # Replace longest tokens first so 'T_inA' isn't pre-eaten by 'T_'.
    for tok in sorted(_PROJECT_SYMBOLS, key=lambda k: -len(k)):
        out = out.replace(tok, _PROJECT_SYMBOLS[tok])
    return out


# ─── Module smoke test ─────────────────────────────────────────────


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    samples = [
        "D_h = 0.42 mm",
        "rho_s = 7900 kg/m^3",
        "mu_f at 40 deg C",
        "m_dot inlet",
        "eps_f = 0.35",
        "T_inA = 350 K, P_inA = 101.3 kPa",
        "Re in [400, 16000]",
    ]
    for s in samples:
        u = to_unicode(s)
        # Print as repr so GBK-locked terminals can dump without crash
        print(f"  {s!r} -> {u!r}")
        # Some inputs intentionally pass through unchanged (ASCII-only
        # symbols that have no Unicode glyph e.g. T_inA stays literal).
    print(f"PASS: greek('mu') = {greek('mu')!r}, greek('rho') = {greek('rho')!r}")
