"""Explicit one-way module boundaries, including imports inside functions."""
import ast
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = {
    'models': ('solvers', 'preprocess', 'postprocess', 'pipelines', 'controllers', 'ui'),
    'preprocess': ('solvers', 'pipelines', 'controllers', 'ui'),
    'solvers/backends': ('preprocess', 'postprocess', 'pipelines', 'controllers', 'ui', 'design', 'optimization', 'core'),
    'postprocess': ('solvers', 'preprocess', 'pipelines', 'controllers', 'ui'),
    'io': ('solvers', 'preprocess', 'pipelines', 'controllers', 'ui'),
}


def forbidden_imports(source, forbidden, package='sjtu_tpmshx'):
    violations = []
    for node in ast.walk(ast.parse(source)):
        modules = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                   [item.name for item in node.names] if isinstance(node, ast.Import) else [])
        if isinstance(node, ast.ImportFrom) and node.level:
            modules = [resolve_name('.' * node.level + (node.module or ''), package)]
        if isinstance(node, ast.ImportFrom):
            modules += [module + '.' + item.name for module in modules[:]
                        for item in node.names if item.name != '*']
        for module in modules:
            if any(module == 'sjtu_tpmshx.' + name or module.startswith('sjtu_tpmshx.' + name + '.')
                   for name in forbidden):
                violations.append((node.lineno, module))
    return violations


def test_implementation_import_boundaries():
    failures = []
    for directory, forbidden in RULES.items():
        for path in (ROOT / directory).rglob('*.py'):
            package = '.'.join(('sjtu_tpmshx', *path.relative_to(ROOT).parts[:-1]))
            for line, module in forbidden_imports(path.read_text(encoding='utf-8'), forbidden, package):
                failures.append(f'{path.relative_to(ROOT)}:{line}: {module}')
    assert not failures, '\n'.join(failures)


def test_checker_detects_nested_illegal_import_and_allows_shared_models():
    source = 'def evaluate():\n    from sjtu_tpmshx.solvers.api import run_case\n'
    assert (2, 'sjtu_tpmshx.solvers.api') in forbidden_imports(source, ('solvers',))
    assert (1, 'sjtu_tpmshx.solvers') in forbidden_imports(
        'from .. import solvers', ('solvers',), 'sjtu_tpmshx.postprocess')
    assert not forbidden_imports('from sjtu_tpmshx.models.catalog import resolve_model', ('solvers',))
