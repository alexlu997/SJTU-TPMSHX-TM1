"""Check the public stage boundaries, including imports inside functions."""
import ast
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import pytest

from sjtu_tpmshx.development.runs.tools.audit_import_graph import LAYERS, import_targets, target_unit, unit_of

ROOT = Path(__file__).resolve().parents[3] / 'python'
RULES = {
    'models': ('solvers', 'preprocess', 'postprocess', 'applications'),
    'df_surrogate': ('solvers', 'preprocess', 'postprocess', 'applications'),
    'preprocess': ('solvers', 'applications'),
    'backend': ('preprocess', 'postprocess', 'applications'),
    'postprocess': ('solvers', 'preprocess', 'applications'),
    'io': ('solvers', 'preprocess', 'applications'),
}


def forbidden_imports(source, forbidden, package='sjtu_tpmshx'):
    violations = []
    for node in ast.walk(ast.parse(source)):
        for module in import_targets(node, package):
            if not module.startswith('sjtu_tpmshx.'):
                continue
            owner = target_unit(module, LAYERS)
            application = module.startswith('sjtu_tpmshx.applications') and owner != 'io'
            if owner in forbidden or ('applications' in forbidden and application):
                violations.append((node.lineno, module))
    return violations


def test_implementation_import_boundaries():
    failures, checked = [], set()
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        owner = unit_of(path)
        if owner == 'solvers' and (relative.parts[0] == 'cpp_interface' or relative.parts[:2] == ('solvers', 'backends')):
            owner = 'backend'
        if owner in RULES:
            checked.add(owner)
            package = '.'.join(('sjtu_tpmshx', *relative.parts[:-1]))
            for line, module in forbidden_imports(path.read_text(encoding='utf-8'), RULES[owner], package):
                failures.append(f'{relative}:{line}: {module}')
    assert checked == RULES.keys()
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize('module', [
    'solvers.api', 'cpp_interface.full_2d_stage', 'cpp_interface.solver_library.full_2d',
    'cpp_interface.native_preparation',
])
def test_checker_detects_imports_across_stage_boundaries(module):
    name = 'sjtu_tpmshx.' + module
    source = f'def evaluate():\n    import {name}\n'
    assert (2, name) in forbidden_imports(source, RULES['postprocess'])


def test_checker_resolves_relative_imports_and_allows_shared_models():
    assert (1, 'sjtu_tpmshx.solvers') in forbidden_imports(
        'from .. import solvers', ('solvers',), 'sjtu_tpmshx.postprocess')
    assert not forbidden_imports('from sjtu_tpmshx.physical_models.catalog import resolve_model', ('solvers',))


@pytest.mark.parametrize('adapter, api', [
    ('cpp_interface.native_preparation', 'preprocess.api'),
    ('preprocess.three_d.preparation', 'preprocess.api'),
    ('cpp_interface.full_2d_stage', 'solvers.execution_record'),
    ('cpp_interface.solver_library.full_3d', 'solvers.execution_record'),
])
def test_stage_adapters_do_not_import_publishers(adapter, api):
    path = ROOT.joinpath(*adapter.split('.')).with_suffix('.py')
    package = 'sjtu_tpmshx.' + adapter.rsplit('.', 1)[0]
    api = 'sjtu_tpmshx.' + api
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        for module in import_targets(node, package):
            assert module != api and not module.startswith(api + '.'), f'{path}:{node.lineno}'


def check_cycles(modules):
    graph = {}
    for module, path in modules.items():
        package = module if path.name == '__init__.py' else module.rsplit('.', 1)[0]
        graph[module] = {
            target
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
            for target in import_targets(node, package)
            if target in modules
        }
    TopologicalSorter(graph).prepare()


@pytest.mark.parametrize('owner', ['solvers', 'ui'])
def test_implementation_imports_have_no_cycles(owner):
    modules = {
        '.'.join(('sjtu_tpmshx', *path.relative_to(ROOT).with_suffix('').parts)).removesuffix('.__init__'): path
        for path in ROOT.rglob('*.py') if unit_of(path) == owner
    }
    assert modules, owner
    check_cycles(modules)


def test_checker_detects_cycle_across_solver_directories(tmp_path):
    api, stage = 'sjtu_tpmshx.solvers.api', 'sjtu_tpmshx.cpp_interface.full_2d_stage'
    modules = {api: tmp_path / 'api.py', stage: tmp_path / 'full_2d_stage.py'}
    modules[api].write_text(f'import {stage}', encoding='utf-8')
    modules[stage].write_text(f'import {api}', encoding='utf-8')
    with pytest.raises(CycleError):
        check_cycles(modules)
