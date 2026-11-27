"""ISO 80000-1 rich-text and Matplotlib symbols for the GUI."""
from __future__ import annotations

IT_STACK = "'Helvetica Neue', 'Arial', sans-serif"
RM_STACK = "'Helvetica Neue', 'PingFang SC', 'Arial', sans-serif"

NB_THIN = "\u202f"   # Non-breaking thin space
MINUS = "\u2212"     # Minus sign
ENDASH = "\u2013"    # En dash for numeric ranges
TIMES = "\u00d7"     # Multiplication sign for dimensions
DELTA = "\u0394"     # Upright capital Delta
RHO = "\u03c1"       # Lowercase Greek rho
PHI = "\u03c6"       # Lowercase Greek phi
EPS = "\u03b5"       # Lowercase Greek epsilon
DELTA_LO = "\u03b4"  # Lowercase Greek delta
MDOT = "m\u0307"     # Mass flow rate m-dot


def it(symbol: str) -> str:
    """Wrap a physical quantity symbol in italic HTML."""
    return f'<span style="font-family:{IT_STACK}; font-style:italic;">{symbol}</span>'


def rm(text: str) -> str:
    """Wrap an upright label, operator, or unit in normal HTML."""
    return f'<span style="font-family:{RM_STACK}; font-style:normal;">{text}</span>'


def sub(text: str, italic: bool = False) -> str:
    """Format an HTML subscript in italic or upright style."""
    inner = it(text) if italic else rm(text)
    return f'<sub style="font-size:74%;">{inner}</sub>'


def qsym(
    base: str,
    subscript: str | None = None,
    sub_italic: bool = False,
    prefix: str = "",
) -> str:
    """Format a physical quantity with an optional upright prefix and subscript."""
    out = (rm(prefix) if prefix else "") + it(base)
    if subscript is not None:
        out += sub(subscript, italic=sub_italic)
    return out


def signed(val: float, fmt: str = "+.3f") -> str:
    """Format a signed number with the true minus sign."""
    return format(val, fmt).replace("-", MINUS)


def fnum_iso(val: float, digits: int = 1) -> str:
    """Format a number with thin-space digit grouping and true minus sign."""
    return f"{val:,.{digits}f}".replace(",", NB_THIN).replace("-", MINUS)


def val_unit(val_str: str, unit: str = "") -> str:
    """Join a formatted value and its unit with a non-breaking thin space."""
    return f"{val_str}{NB_THIN}{unit}" if unit else val_str


def rng(lo_str: str, hi_str: str, unit: str | None = None) -> str:
    """Format a numeric range with an en dash and an optional unit."""
    text = f"{lo_str}{ENDASH}{hi_str}"
    return val_unit(text, unit) if unit else text


SYM: dict[str, str] = {
    "u": qsym("u"),
    "u_A": qsym("u", "A"),
    "u_B": qsym("u", "B"),
    "vmag_A": f'{rm("|")}{it("u")}{rm("|")}{sub("A")}',
    "vmag_B": f'{rm("|")}{it("u")}{rm("|")}{sub("B")}',
    "T_in": qsym("T", "in"),
    "T_out": qsym("T", "out"),
    "P": qsym("P"),
    "P_in": qsym("P", "in"),
    "k_s": qsym("k", "s"),
    "T": qsym("T"),
    "T_fA": qsym("T", "f,A"),
    "T_fB": qsym("T", "f,B"),
    "T_s": qsym("T", "s"),
    "Q": qsym("Q"),
    "dP_A": qsym("P", "A", prefix=DELTA),
    "dP_B": qsym("P", "B", prefix=DELTA),
    "dP_rel": f'{qsym("P", prefix=DELTA)}/{it("P")}',
    "dP_dL": f'{rm("d")}{it("P")}/{rm("d")}{it("L")}',
    "m_A": qsym(MDOT, "A"),
    "m_B": qsym(MDOT, "B"),
    "x": qsym("x"),
    "y": qsym("y"),
    "z": qsym("z"),
    "xy": f'{it("x")}{it("y")}',
    "xz": f'{it("x")}{it("z")}',
    "yz": f'{it("y")}{it("z")}',
    "L": qsym("L"),
    "L_cell": qsym("L", "cell"),
    "L_x": qsym("L", "x", sub_italic=True),
    "L_y": qsym("L", "y", sub_italic=True),
    "L_z": qsym("L", "z", sub_italic=True),
    "t": qsym("t"),
    "W": qsym("W"),
    "H": qsym("H"),
    "V": qsym("V"),
    "W_H": f'{it("W")}{NB_THIN}{TIMES}{NB_THIN}{it("H")}',
    "rho": it(RHO),
    "rho_s": qsym(RHO, "s"),
    "eps": it(EPS),
    "A_0": qsym("A", "0"),
    "D_h": qsym("D", "h"),
    "K_ss": qsym("K", "ss"),
    "T_out_A": qsym("T", "out,A"),
    "T_out_B": qsym("T", "out,B"),
    "phi": it(PHI),
    "delta": it(DELTA_LO),
    "C": it("C"),
    "Re": it("Re"),
    "Nu": it("Nu"),
    "Re_hot": f'{it("Re")}{sub("hot")}',
    "Re_cold": f'{it("Re")}{sub("cold")}',
}

MPL: dict[str, str] = {
    "x_mm": r"$\mathit{x}\ \mathrm{[mm]}$",
    "y_mm": r"$\mathit{y}\ \mathrm{[mm]}$",
    "z_mm": r"$\mathit{z}\ \mathrm{[mm]}$",
    "T_K": r"$\mathit{T}\ \mathrm{[K]}$",
    "T_fA": r"$\mathit{T}_{\mathrm{f{,}A}}$",
    "T_fB": r"$\mathit{T}_{\mathrm{f{,}B}}$",
    "T_s": r"$\mathit{T}_{\mathrm{s}}$",
    "plus_x": r"$+\mathit{x}$",
    "minus_y": r"$-\mathit{y}$",
    "V_L": r"芯体体积 $\mathit{V}\ \mathrm{[L]}$",
    "dP_pct": r"压损 $\Delta\mathit{P}/\mathit{P}\ \mathrm{[\%]}$",
    "pr_ratio": r"← 更低     平均相对压降 $\Delta\mathit{P}/\Delta\mathit{P}_0\ \mathrm{[1]}$",
    "hg_pct": r"平均有效换热提升 $\Delta\mathit{Q}/\mathit{Q}_0\ \mathrm{[\%]}$     更高 →",
}


def mpl_qd_row(topo: str, l_val: float, t_val: float) -> str:
    """Format a Quick Design row label for Matplotlib axes."""
    return rf"{topo}  $\mathit{{L}}$ {l_val:g} · $\mathit{{t}}$ {t_val:g}"
