"""Static import-graph audit for the sjtu_tpmshx package (P1.1, 2026-07-19).

AST-based — no module is actually imported, so Qt/numba side effects can't
bite. Handles BOTH import conventions used in this repo: top-level style
(``from solvers.x import y``, enabled by the various sys.path bootstraps)
and package style (``from sjtu_tpmshx.solvers.x import y``), plus relative
imports.

Usage (from repo root):
    python -u sjtu_tpmshx/runs/tools/audit_import_graph.py
    python -u sjtu_tpmshx/runs/tools/audit_import_graph.py --fail-on-violations  # CI gate mode

The layer model below encodes the INTENDED dependency direction (lower may
never import higher). validation/runs/tests are "free" consumers: they may
import anything, but nothing outside their tier may import them.
"""
from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]          # .../sjtu_tpmshx
REPO = PKG.parent

# intended layering: unit -> layer index (lower = more fundamental)
LAYERS = {
    "logutil": 0, "configs": 0, "domain": 0,
    "models": 0.5, "solvers": 1, "preprocess": 2,
    "df_surrogate": 2, "design": 2,
    "pipelines": 3, "core": 3, "optimization": 3,
    "controllers": 4,
    "ui": 5, "main": 5,
}
FREE = {"validation", "runs", "tests", "poc"}       # may import anything

# Adjudicated upward edges (P1.9, 2026-07-20) — ACCEPTED with rationale,
# reported separately, never counted as violations. Adding an entry here is
# an architecture decision: cite it in docs/ARCHITECTURE-AUDIT-2026-07.md.
SANCTIONED = {
    ("models", "df_surrogate"):
        "shared physical models consume the existing versioned DF closure; "
        "TM1 extraction preserves the previously sanctioned closure boundary. "
        "No numerical backend is imported by the model entry points.",
    ("solvers", "df_surrogate"):
        "closure boundary: solvers consume predict_K_cF* and the _domain "
        "training-hull constants, while df_surrogate imports solvers "
        "geometry helpers (a mutual pair). Extracting a closure-interface "
        "layer is P1.8b-scale restructuring - deliberately accepted as-is.",
    ("domain", "df_surrogate"):
        "df_surrogate/_domain.py is a leaf constants module (training-grid "
        "nodes); domain/validator reads the single source. Direction is "
        "nominal, no behavior coupling.",
}


def discover_units() -> set[str]:
    units = set()
    for child in PKG.iterdir():
        if child.is_dir() and child.name != "__pycache__":
            units.add(child.name)
        elif child.suffix == ".py":
            units.add(child.stem)
    return units


def unit_of(py: Path) -> str:
    rel = py.relative_to(PKG)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def resolve_relative(py: Path, level: int, module: str | None) -> str | None:
    """Return the target top-level unit of a relative import, or None."""
    pkg_parts = list(py.relative_to(PKG).parts[:-1])       # package path of the file
    if level - 1 > len(pkg_parts):
        return None                                        # climbs out of the package
    base = pkg_parts[: len(pkg_parts) - (level - 1)]
    tail = module.split(".") if module else []
    full = base + tail
    return full[0] if full else None


def target_unit(name: str, units: set[str]) -> str | None:
    parts = name.split(".")
    if parts[0] == "sjtu_tpmshx":
        parts = parts[1:]
    if parts and parts[0] in units:
        return parts[0]
    return None


def main() -> int:
    units = discover_units()
    edges: Counter[tuple[str, str]] = Counter()
    edge_files: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    parse_errors: list[str] = []

    for py in sorted(PKG.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        src_unit = unit_of(py)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:                          # pragma: no cover
            parse_errors.append(f"{py}: {exc}")
            continue
        for node in ast.walk(tree):
            targets: list[str | None] = []
            if isinstance(node, ast.Import):
                targets = [target_unit(a.name, units) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    targets = [resolve_relative(py, node.level, node.module)]
                elif node.module:
                    targets = [target_unit(node.module, units)]
            for dst in targets:
                if dst and dst != src_unit and dst in units:
                    edges[(src_unit, dst)] += 1
                    edge_files[(src_unit, dst)].add(
                        str(py.relative_to(REPO)).replace("\\", "/"))

    core_edges = {e: n for e, n in edges.items()
                  if e[0] not in FREE and e[1] not in FREE}
    violations: list[str] = []
    sanctioned_hits: list[str] = []
    for (src, dst), n in sorted(edges.items()):
        if src in FREE:
            continue                                        # free consumers
        if (src, dst) in SANCTIONED:
            sanctioned_hits.append(
                f"{src} -> {dst} ({n}x): {SANCTIONED[(src, dst)]}")
            continue
        if dst in FREE:
            violations.append(
                f"{src} -> {dst} ({n}x): non-free unit imports a free tier "
                f"(files: {sorted(edge_files[(src, dst)])[:3]})")
        elif src in LAYERS and dst in LAYERS and LAYERS[src] < LAYERS[dst]:
            violations.append(
                f"{src} (L{LAYERS[src]}) -> {dst} (L{LAYERS[dst]}) ({n}x): "
                f"UPWARD import (files: {sorted(edge_files[(src, dst)])[:3]})")

    print(f"units discovered: {sorted(units)}")
    print(f"\n== core edge list (non-free -> non-free, {len(core_edges)} edges) ==")
    for (src, dst), n in sorted(core_edges.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {src:14s} -> {dst:14s} {n:4d}")
    print("\n== fan-in / fan-out (core units) ==")
    fan_in: Counter[str] = Counter(); fan_out: Counter[str] = Counter()
    for (src, dst), n in core_edges.items():
        fan_out[src] += n; fan_in[dst] += n
    for u in sorted(set(fan_in) | set(fan_out)):
        print(f"  {u:14s} in={fan_in[u]:4d}  out={fan_out[u]:4d}")
    print("\n== free-tier consumption (tests/validation/runs -> core, edges only) ==")
    for (src, dst), n in sorted(edges.items()):
        if src in FREE and dst not in FREE:
            print(f"  {src:14s} -> {dst:14s} {n:4d}")
    print(f"\n== SANCTIONED edges ({len(sanctioned_hits)}) ==")
    for s_ in sanctioned_hits:
        print(f"  {s_}")
    print(f"\n== VIOLATIONS ({len(violations)}) ==")
    for v in violations:
        print(f"  {v}")
    if parse_errors:
        print(f"\n== parse errors ({len(parse_errors)}) ==")
        for e in parse_errors:
            print(f"  {e}")
    if "--fail-on-violations" in sys.argv and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
