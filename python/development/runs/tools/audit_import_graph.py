"""Static import-graph audit for the tm1 package (P1.1, 2026-07-19).

AST-based — no module is actually imported, so GUI side effects cannot
bite. Recognises current package-qualified and relative imports, plus historical
top-level imports when auditing old source. That recognition does not make old
``from solvers.x import y`` paths supported runtime entry points.

Usage (from repo root):
    python -m tm1.development.runs.tools.audit_import_graph
    python -m tm1.development.runs.tools.audit_import_graph --fail-on-violations

The audit also rejects import cycles between the modules of each owner in
``CYCLE_OWNERS`` and prints the cycle path.

The layer model below encodes the INTENDED dependency direction (lower may
never import higher). validation/runs/tests are "free" consumers: they may
import anything, but nothing outside their tier may import them.
"""
from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from graphlib import CycleError, TopologicalSorter
from importlib.util import resolve_name
from pathlib import Path

PKG = Path(__file__).resolve().parents[3]          # Python source directory
REPO = PKG.parent

# intended layering: unit -> layer index (lower = more fundamental)
LAYERS = {
    "logutil": 0, "configs": 0, "domain": 0, "native_values": 0,
    "models": 0.5, "result_math": 0.5, "result_display": 0.5,
    "solvers": 1, "preprocess": 2, "postprocess": 2,
    "df_surrogate": 2, "design": 2, "io": 2,
    "pipelines": 3, "optimization": 3, "workflows": 3, "compute": 3,
    "controllers": 4,
    "result_adapter": 4,
    "ui": 5, "main": 5, "cli": 5,
}
FREE = {"validation", "runs", "tests", "poc"}       # may import anything

# Directory groups keep each existing dependency owner separate.
OWNERS = {
    "physical_models.df_surrogate": "df_surrogate",
    "physical_models.range_policy": "domain",
    "physical_models": "models",
    "postprocess.result_display": "result_display",
    "postprocess.result_math": "result_math",
    "run_control.logutil": "logutil",
    "run_control": "domain",
    "data_types": "domain",
    "file_io.text_file": "domain",
    "file_io": "io",
    "model_configs": "configs",
    "applications.cli.cli_options": "io",
    "cpp_interface": "native_values",
    **{f"applications.gui.{name}": name for name in ("main", "ui", "controllers")},
    **{f"applications.{name}": name for name in (
        "design", "optimization", "cli", "result_adapter")},
    "applications.execution": "workflows",
    **{f"development.{name}": name for name in ("tests", "validation", "runs")},
}

# Adjudicated upward edges (P1.9, 2026-07-20) — ACCEPTED with rationale,
# reported separately, never counted as violations. Adding an entry here is
# an architecture decision: document it in docs/architecture.md.
_SOLVER_DF_EDGE = ("solvers", "df_surrogate")
SANCTIONED = {
    ("models", "df_surrogate"):
        "shared physical models consume the existing versioned DF closure; "
        "TM1 extraction preserves the previously sanctioned closure boundary. "
        "No numerical backend is imported by the model entry points.",
    _SOLVER_DF_EDGE:
        "The 3D solver host reads the CFD campaign and scope labels from the D-F model for result metadata.",
}


def source_paths():
    roots = (PKG, REPO / 'tests/python') if PKG.name == 'python' else (PKG,)
    for directory in roots:
        yield from (path for path in directory.rglob('*.py') if '__pycache__' not in path.parts)


def discover_units() -> set[str]:
    return {unit_of(path) for path in source_paths()}


def unit_of(py: Path) -> str:
    if py.is_relative_to(PKG.parent / 'tests/python'):
        return 'tests'
    rel = py.relative_to(PKG)
    name = '.'.join(rel.with_suffix('').parts).removesuffix('.__init__')
    for prefix, owner in OWNERS.items():
        if name == prefix or name.startswith(prefix + '.'):
            return owner
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def import_targets(node: ast.AST, package: str) -> list[str]:
    """Resolve import spellings without importing or evaluating source."""
    if isinstance(node, ast.Import):
        return [item.name for item in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module or ''
        if node.level:
            module = resolve_name('.' * node.level + module, package)
        return [module, *(module + '.' + item.name for item in node.names
                          if item.name != '*')]
    return []


def _policy_targets(node: ast.AST, package: str) -> list[str]:
    targets = import_targets(node, package)
    if isinstance(node, ast.ImportFrom) and targets[0] == "tm1.physical_models" and len(targets) > 1:
        # Classify named physical_models submodules by their own owners.
        return targets[1:]
    return targets


def target_unit(name: str, units: set[str]) -> str | None:
    parts = name.split(".")
    if parts[0] == "tm1":
        parts = parts[1:]
    elif parts[0] in sys.stdlib_module_names:
        return None
    name = '.'.join(parts)
    for prefix, owner in OWNERS.items():
        if name == prefix or name.startswith(prefix + '.'):
            return owner if owner in units else None
    if parts and parts[0] in units:
        return parts[0]
    return None


_DTO_PACKAGES = {"tm1.data_types", "data_types"}
_STAGE_DTO_MODULES = {
    f"{package}.{module}" for package in _DTO_PACKAGES
    for module in ("case_data", "model_refs", "field_result", "metric_spec", "performance_result")
}
_STAGE_DTO_TYPES = {"CaseData", "FieldResult", "MetricSpec", "MetricValue", "PerformanceResult", "ModelRef"}
_OTHER_STAGE_MODULES = {"full_2d_stage", "full_3d_stage", "run_state", "native_preparation", "preparation_host",
                        "inlet_properties", "quick_design", "_native_preparation_3d", "quick_preparation"}
_FULL_2D_FORBIDDEN_SIBLINGS = {"full_3d_stage", "quick_design", "native_preparation", "inlet_properties",
                               "result_evaluation", "_native_preparation_3d", "quick_preparation", "*"}
_FULL_3D_FORBIDDEN_SIBLINGS = {"full_2d_stage", "quick_design", "native_preparation", "inlet_properties",
                               "result_evaluation", "_native_preparation_3d", "quick_preparation", "*"}
_QUICK_PREPARATION_IMPORTS = {"tm1.cpp_interface.quick_preparation"}
# Shared ABI layouts use wire types from _native_df and _native_result.
_FULL_PREPARATION_WIRE_MODULES = {
    "native_preparation", "preparation_host", "inlet_properties", "stage_libraries",
    "_native_preparation_case", "_native_preparation_3d", "_native_values", "_native_properties",
    "_native_df", "_native_result", "_native_diagnostics",
}
_TYPE_GUARDS = {"typing.TYPE_CHECKING", "typing_extensions.TYPE_CHECKING"}
_BINDING_NAMESPACES = {"tm1", "tm1.cpp_interface", *_DTO_PACKAGES,
                       "typing", "typing_extensions", *_TYPE_GUARDS}


def _invalid_stage_target(host, target, binding, operations):
    if not target.startswith("tm1."):
        return False
    area, _, member = target.removeprefix("tm1.").partition(".")
    module, _, name = member.partition(".")
    if binding == "solver_api":
        return area == "cpp_interface" and bool(module)
    if binding == "native_preparation":
        if host and not operations and area == "cpp_interface":
            # The public API reaches these native operations through the stage host.
            return module in _FULL_PREPARATION_WIRE_MODULES
        if host and operations and area == "preprocess" and module == "quick_design":
            return True
        if not host and area == "cpp_interface" and module:
            return module not in _FULL_PREPARATION_WIRE_MODULES
    if binding in {"quick_design", "quick_preparation"}:
        if area == "cpp_interface" and module != binding and module in _OTHER_STAGE_MODULES:
            return True
    elif binding in {"full_2d_stage", "full_3d_stage"}:
        forbidden_siblings = _FULL_2D_FORBIDDEN_SIBLINGS if binding == "full_2d_stage" else _FULL_3D_FORBIDDEN_SIBLINGS
        if area == "cpp_interface" and module in forbidden_siblings:
            return True
    if host:
        return area == "cpp_interface" and bool(module) and (
            module != binding or name.partition(".")[0] not in operations)
    return (area in {"applications", "compute", "file_io", "physical_models",
                     "postprocess", "preprocess", "solvers", "*"}
            or (area == "data_types" and module == "*"))


def _dto_import(target, modules, types):
    owner, _, name = target.rpartition(".")
    return target in modules or owner in modules or name in types


def _qualified_names(node, aliases):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return set()
    suffix = "".join("." + part for part in reversed(parts))
    return {name + suffix if name else "" for name in aliases.get(node.id, ())}


def _possible_names(paths):
    # An empty name denotes a local value on a path without that import.
    return {name: set().union(*(path.get(name, {""}) for path in paths))
            for name in set().union(*paths)}


class _StageImportAudit(ast.NodeVisitor):
    """Check host access to native operations. Permit DTO imports in the binding only for type checking."""

    def __init__(self, host, package, binding, operations, dto_modules, dto_types):
        self.binding = binding
        self.operations = operations
        self.dto_modules = dto_modules
        self.dto_types = dto_types
        self.host = host
        self.package = package
        self.aliases = {}
        self.module_names = self.aliases
        self.class_parent = None
        self.functions = []
        self.violations = []

    def bind(self, name, targets):
        # The binding needs only package names and type guards to check its imports.
        if not self.host:
            targets = {target if target in _BINDING_NAMESPACES else "" for target in targets}
        if targets and targets != {""}:
            self.aliases[name] = targets
        else:
            self.aliases.pop(name, None)

    def scope(self, nodes, aliases):
        outer = self.aliases, self.functions, self.class_parent
        self.aliases, self.functions, self.class_parent = aliases, [], None
        for node in nodes:
            self.visit(node)
        # Functions can use imports that follow their definitions.
        for function in self.functions:
            local = aliases.copy()
            args = function.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
                if arg is not None:
                    local.pop(arg.arg, None)
            body = [function.body] if isinstance(function, ast.Lambda) else function.body
            self.scope(body, local)
        self.aliases, self.functions, self.class_parent = outer

    def visit_Import(self, node):
        targets = import_targets(node, self.package)
        if (self.binding == "native_preparation" and isinstance(node, ast.ImportFrom)
                and node.names[0].name == "*" and targets[0].split(".", 1)[0] == "tm1"):
            self.violations.append((node.lineno, targets[0] + ".*"))
        if not self.host:
            # Report the imported member when the statement names one.
            forbidden = next((name for name in reversed(targets) if _dto_import(name, self.dto_modules, self.dto_types)), None)
            if forbidden:
                self.violations.append((node.lineno, forbidden))
        for item in node.names:
            if item.name == "*":
                if targets[0] + ".TYPE_CHECKING" in _TYPE_GUARDS:
                    self.bind("TYPE_CHECKING", {targets[0] + ".TYPE_CHECKING"})
                continue
            if isinstance(node, ast.ImportFrom):
                self.bind(item.asname or item.name, {targets[0] + "." + item.name})
            else:
                root = item.name.partition(".")[0]
                self.bind(item.asname or root, {item.name if item.asname else root})

    visit_ImportFrom = visit_Import

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load):
            self.aliases.pop(node.id, None)

    def visit_Global(self, node):
        for name in node.names:
            self.bind(name, self.module_names.get(name, set()))

    def visit_Attribute(self, node):
        targets = _qualified_names(node, self.aliases)
        for target in sorted(targets):
            # A loaded DTO module or exported class is also available through its parent package.
            if (_invalid_stage_target(self.host, target, self.binding, self.operations)
                    or (not self.host and isinstance(node.ctx, ast.Load) and (
                        target in self.dto_modules
                        or (target.rpartition(".")[0] in _DTO_PACKAGES and target.rpartition(".")[2] in self.dto_types)))):
                self.violations.append((node.lineno, target))
        self.visit(node.value)

    def type_guard(self, test):
        guard = _qualified_names(test, self.aliases)
        if guard and guard <= _TYPE_GUARDS:
            return False
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            value = self.type_guard(test.operand)
            return None if value is None else not value
        if isinstance(test, ast.BoolOp):
            stop = isinstance(test.op, ast.Or)
            values = [self.type_guard(part) for part in test.values]
            if stop in values:
                return stop
            if None not in values:
                return not stop
        return None

    def visit_BoolOp(self, node):
        stop = isinstance(node.op, ast.Or)
        for part in node.values:
            self.visit(part)
            if self.type_guard(part) is stop:
                break

    def visit_If(self, node):
        self.visit(node.test)
        guard = self.type_guard(node.test)
        if guard is not None:
            for statement in (node.body if guard else node.orelse):
                self.visit(statement)
        else:
            self.branches(((node.body, self.aliases), (node.orelse, self.aliases)))

    def branches(self, paths):
        outer = self.aliases
        outcomes = []
        for statements, names in paths:
            self.aliases = names.copy()
            for statement in statements:
                self.visit(statement)
            outcomes.append(self.aliases)
        outer.clear()
        outer.update(_possible_names(outcomes))
        self.aliases = outer

    def visit_Try(self, node):
        possible = [self.aliases.copy()]
        for statement in node.body:
            self.visit(statement)
            possible.append(self.aliases.copy())
        failure = _possible_names(possible)
        paths = [(node.orelse, self.aliases)]
        paths.extend(((handler,), failure) for handler in node.handlers)
        self.branches(paths)
        for statement in node.finalbody:
            self.visit(statement)

    visit_TryStar = visit_Try

    def visit_FunctionDef(self, node):
        defaults = (*node.args.defaults, *node.args.kw_defaults)
        for expr in (*getattr(node, "decorator_list", ()), *defaults):
            if expr is not None:
                self.visit(expr)
        if not isinstance(node, ast.Lambda):
            self.aliases.pop(node.name, None)
        self.functions.append(node)

    visit_AsyncFunctionDef = visit_Lambda = visit_FunctionDef

    def visit_ClassDef(self, node):
        for expr in (*node.decorator_list, *node.bases, *node.keywords):
            self.visit(expr)
        # Methods and comprehension bodies use the enclosing function or module names.
        outer = self.aliases, self.class_parent
        if self.class_parent is None:
            self.class_parent = self.aliases
        self.aliases = self.class_parent.copy()
        for statement in node.body:
            self.visit(statement)
        self.aliases, self.class_parent = outer
        self.aliases.pop(node.name, None)

    def visit_ListComp(self, node):
        first, *rest = node.generators
        self.visit(first.iter)
        inner = [first.target, *first.ifs]
        for clause in rest:
            inner.extend((clause.iter, clause.target, *clause.ifs))
        inner.extend((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,))
        enclosing = self.aliases if self.class_parent is None else self.class_parent
        self.scope(inner, enclosing.copy())

    visit_DictComp = visit_SetComp = visit_GeneratorExp = visit_ListComp

    def visit_Assign(self, node):
        if node.value is None:
            return
        self.visit(node.value)
        alias = _qualified_names(node.value, self.aliases) if self.host else set()
        for target in (node.targets if isinstance(node, ast.Assign) else (node.target,)):
            self.visit(target)
            if alias and isinstance(target, ast.Name):
                self.bind(target.id, alias)

    visit_AnnAssign = visit_NamedExpr = visit_Assign

    def visit_TypeAlias(self, node):
        self.visit(node.name)

    def visit_For(self, node):
        self.visit(node.iter)
        self.branches([((), self.aliases), ([node.target, *node.body], self.aliases)])
        for statement in node.orelse:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self.visit(node.test)
        if self.type_guard(node.test) is not False:
            self.branches([((), self.aliases), (node.body, self.aliases)])
        for statement in node.orelse:
            self.visit(statement)

    def visit_ExceptHandler(self, node):
        if node.type is not None:
            self.visit(node.type)
        self.aliases.pop(node.name, None)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node):
        self.generic_visit(node)
        self.aliases.pop(node.rest if isinstance(node, ast.MatchMapping) else node.name, None)

    visit_MatchMapping = visit_MatchStar = visit_MatchAs


def _stage_boundary_violations(path, tree, package):
    preparation_api = path == PKG / "preprocess/api.py"
    if preparation_api or path == PKG / "applications/design/sizing.py":
        for node in ast.walk(tree):
            for target in import_targets(node, package):
                if target in _QUICK_PREPARATION_IMPORTS:
                    yield f"{path.relative_to(REPO)}:{node.lineno}: Quick preparation boundary -> {target}"
                    break
        if not preparation_api:
            return
    if path == PKG / "solvers/api.py":
        label, binding, operations = "solver API", "solver_api", set()
    elif (preparation_api or path == PKG / "preprocess/two_d/preparation.py" or path.parent == PKG / "cpp_interface"
            and path.stem in {"native_preparation", "preparation_host", "inlet_properties",
                              "_native_preparation_3d", "_native_preparation_case"}):
        label, binding = "full preparation", "native_preparation"
        operations = set() if preparation_api else {"", "pack_input", "run_preparation"}
    elif path == PKG / "preprocess/three_d/preparation.py":
        label, binding = "full 3D preparation", "native_preparation"
        operations = {"", "pack_volume_input", "run_volume_preparation"}
    elif path in (PKG / "preprocess/quick_design.py", PKG / "cpp_interface/quick_preparation.py"):
        label, binding, operations = "Quick preparation", "quick_preparation", {"", "run_preparation"}
    elif path in (PKG / "solvers/quick_design.py", PKG / "cpp_interface/quick_design.py"):
        label, binding, operations = "Quick solve", "quick_design", {"", "QuickSolver"}
    elif path in (PKG / "solvers/full_2d.py", PKG / "cpp_interface/full_2d_stage.py"):
        label, binding = "full 2D solve", "full_2d_stage"
        operations = {"", "StageDriver", "borrow_mesh", "stage_entries", "check_experiment",
                      "run_stage", "zone_temperatures"}
    elif path in (PKG / "solvers/full_3d.py", PKG / "cpp_interface/full_3d_stage.py"):
        label, binding = "full 3D solve", "full_3d_stage"
        operations = {"", "open_library", "borrow_mesh", "require_saved_stage",
                      "execution_view_query", "run_saved"}
    elif (path.parent == PKG / "postprocess" and path.stem in {"api", "evaluation"}
          or path.parent == PKG / "cpp_interface" and path.stem in {"_native_result_stage", "result_evaluation"}):
        label, binding = "independent result", "result_evaluation"
        operations = {"", "query_result", "METRICS", "APPLICABILITY", "PHYSICAL_BALANCE", "QUALIFICATION"}
    elif path.is_relative_to(PKG / "cpp_interface"):
        label, binding, operations = "native binding", "cpp_interface", set()
    else:
        return
    host = not path.is_relative_to(PKG / "cpp_interface")
    if host:
        modules, types = set(), set()
    else:
        modules, types = _STAGE_DTO_MODULES, _STAGE_DTO_TYPES
        if path == PKG / "cpp_interface/preparation_host.py":
            # The shared solver input packer checks the type of a saved ModelRef.
            modules = {name for name in modules if not name.endswith(".model_refs")}
            types = types - {"ModelRef"}
    for node in ast.walk(tree):
        targets = _policy_targets(node, package)
        if (((not host and binding != "native_preparation")
             or binding in {"full_2d_stage", "full_3d_stage", "solver_api"}
             or (host and binding in {"quick_design", "quick_preparation"}))
                and isinstance(node, ast.ImportFrom) and node.names[0].name == "*"):
            targets.append(targets[0] + ".*")
        forbidden = next((name for name in targets
                          if _invalid_stage_target(host, name, binding, operations)), None)
        if forbidden:
            yield f"{path.relative_to(REPO)}:{node.lineno}: {label} boundary -> {forbidden}"
    references = _StageImportAudit(host, package, binding, operations, modules, types)
    references.scope(tree.body, references.aliases)
    for line, target in references.violations:
        yield f"{path.relative_to(REPO)}:{line}: {label} boundary -> {target}"


# Owners whose modules must have no import cycle. Module-level edges, not owner edges.
CYCLE_OWNERS = ("solvers", "ui")


def owner_modules(owner: str) -> dict[str, Path]:
    return {'.'.join(('tm1', *path.relative_to(PKG).with_suffix('').parts)).removesuffix('.__init__'): path
            for path in PKG.rglob('*.py') if unit_of(path) == owner}


def check_cycles(modules: dict[str, Path]) -> None:
    """Raise CycleError when the modules import each other in a cycle.

    args[1] is the cycle path in import order: each module imports the next one.
    """
    # Each module maps to its importers, so that TopologicalSorter reports the path in import order.
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, path in modules.items():
        package = module if path.name == '__init__.py' else module.rsplit('.', 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            for target in import_targets(node, package):
                if target in modules:
                    graph[target].add(module)
    TopologicalSorter(graph).prepare()


def _is_sanctioned(edge: tuple[str, str], path: Path, node: ast.AST, module: str) -> bool:
    if edge != _SOLVER_DF_EDGE:
        return edge in SANCTIONED
    return (
        path == PKG / 'solvers/full_3d.py'
        and isinstance(node, ast.ImportFrom)
        and module == 'tm1.physical_models.df_surrogate'
        and sorted(alias.name for alias in node.names) == ['CFD_CAMPAIGN', 'CFD_SCOPE']
    )


def main() -> int:
    units = discover_units()
    edges: Counter[tuple[str, str]] = Counter()
    sanctioned: Counter[tuple[str, str]] = Counter()
    edge_files: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    parse_errors: list[str] = []
    violations: list[str] = []

    for py in sorted(source_paths()):
        src_unit = unit_of(py)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:                          # pragma: no cover
            parse_errors.append(f"{py}: {exc}")
            continue
        package = ('.'.join(py.relative_to(PKG.parent).parts[:-1]) if src_unit == 'tests' and not py.is_relative_to(PKG)
                   else '.'.join(('tm1', *py.relative_to(PKG).parts[:-1])))
        violations.extend(_stage_boundary_violations(py, tree, package))
        for node in ast.walk(tree):
            names = _policy_targets(node, package)
            targets = {target_unit(name, units) for name in names}
            for dst in targets:
                if dst and dst != src_unit and dst in units:
                    edge = (src_unit, dst)
                    edges[edge] += 1
                    if _is_sanctioned(edge, py, node, names[0]):
                        sanctioned[edge] += 1
                    else:
                        edge_files[edge].add(py.relative_to(REPO).as_posix())

    for owner in CYCLE_OWNERS:
        try:
            check_cycles(owner_modules(owner))
        except CycleError as error:
            violations.append(f"import cycle in {owner}: {' -> '.join(error.args[1])}")

    core_edges = {e: n for e, n in edges.items()
                  if e[0] not in FREE and e[1] not in FREE}
    for (src, dst), n in sorted((edges - sanctioned).items()):
        if src in FREE:
            continue                                        # free consumers
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
    print(f"\n== SANCTIONED edges ({len(sanctioned)}) ==")
    for (src, dst), n in sorted(sanctioned.items()):
        print(f"  {src} -> {dst} ({n}x): {SANCTIONED[src, dst]}")
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
