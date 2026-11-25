"""Check import boundaries, layer policy, and published module identity."""
import ast
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
import subprocess
import sys

import pytest

from sjtu_tpmshx.development.runs.tools import audit_import_graph as audit
from sjtu_tpmshx.development.runs.tools.audit_import_graph import LAYERS, import_targets, target_unit, unit_of
from tests.python.packaging_support import PUBLIC_NAME_CHECK

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / 'python'
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
    'solvers.api', 'cpp_interface.full_2d_stage', 'cpp_interface.full_3d_stage',
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


@pytest.mark.parametrize('source, forbidden', [
    ('run_control.run_warnings', 'cpp_interface'),
    ('cpp_interface.native_preparation', 'preprocess.api'),
    ('cpp_interface.native_preparation', 'preprocess.two_d.preparation'),
    ('preprocess.two_d.preparation', 'preprocess.api'),
    ('preprocess.three_d.preparation', 'preprocess.api'),
    ('cpp_interface.full_2d_stage', 'solvers.execution_record'),
    ('cpp_interface.full_3d_stage', 'solvers.execution_record'),
])
def test_module_import_boundaries(source, forbidden):
    path = ROOT.joinpath(*source.split('.')).with_suffix('.py')
    package = 'sjtu_tpmshx.' + source.rsplit('.', 1)[0]
    forbidden = 'sjtu_tpmshx.' + forbidden
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        for module in import_targets(node, package):
            assert module != forbidden and not module.startswith(forbidden + '.'), f'{path}:{node.lineno}'


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


def test_configuration_and_native_properties_have_no_import_cycle():
    names = ('data_types.compute_config', 'file_io.config_io', 'file_io.text_file',
             'cpp_interface._native_df', 'cpp_interface._native_properties')
    check_cycles({'sjtu_tpmshx.' + name: ROOT.joinpath(*name.split('.')).with_suffix('.py')
                  for name in names})


def test_checker_detects_cycle_across_solver_directories(tmp_path):
    api, stage = 'sjtu_tpmshx.solvers.api', 'sjtu_tpmshx.cpp_interface.full_2d_stage'
    modules = {api: tmp_path / 'api.py', stage: tmp_path / 'full_2d_stage.py'}
    modules[api].write_text(f'import {stage}', encoding='utf-8')
    modules[stage].write_text(f'import {api}', encoding='utf-8')
    with pytest.raises(CycleError):
        check_cycles(modules)


# Each probe runs in a new interpreter so that this module's imports cannot fill sys.modules.
@pytest.mark.parametrize('probe', [
    "import sjtu_tpmshx.physical_models.df_surrogate.predict\n"
    "bad = {'sjtu_tpmshx.physical_models.tpms_calc', 'sjtu_tpmshx.physical_models.tpms_props'} & set(sys.modules)\n"
    "assert not bad, f'df_surrogate pulled kernel modules: {bad}'",
    "import sjtu_tpmshx.physical_models.tpms_props\n"
    "bad = [m for m in sys.modules if m.startswith('sjtu_tpmshx.physical_models.df_surrogate')"
    " or m.startswith('sjtu_tpmshx.solvers') or m == 'sjtu_tpmshx.physical_models.tpms_calc']\n"
    "if bad: raise SystemExit(f'tpms_props imported upper modules: {bad}')",
    "import sjtu_tpmshx.preprocess.api, sjtu_tpmshx.solvers.api\n"
    "import sjtu_tpmshx.preprocess.two_d.preparation, sjtu_tpmshx.preprocess.three_d.preparation\n"
    "bad = [m for m in sys.modules if m.startswith('sjtu_tpmshx.applications.gui.controllers')]\n"
    "assert not bad, f'preparation pulled controllers: {bad}'",
    "from sjtu_tpmshx.data_types.compute_config import ComputeConfig, ZoneInputConfig\n"
    "from sjtu_tpmshx.data_types.validator import validate_geometry\n"
    "spec = dict(n_ctrl_x=1, n_ctrl_y=1, spline_order=1, symmetric_y=False,\n"
    "            x_decision=[7., .5], L_bounds=[4., 8.], t_bounds=[.3, .6])\n"
    "ComputeConfig(zones=ZoneInputConfig(enabled=True, axis='continuous', config=spec)).validate_static_inputs()\n"
    "validate_geometry(.1, .1, None, 7., .5)\n"
    "if 'sjtu_tpmshx.physical_models' in sys.modules: raise SystemExit('Geometry validation imported physical models')",
], ids=['df-surrogate-below-kernel', 'tpms-props-leaf', 'preparation-without-controllers', 'geometry-validation'])
def test_lower_modules_import_without_upper_modules(probe):
    result = subprocess.run([sys.executable, '-c', 'import sys\n' + probe], cwd=REPO,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_package_has_no_unsanctioned_layer_violations(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['audit_import_graph', '--fail-on-violations'])
    assert audit.main() == 0, capsys.readouterr().out[-2000:]


def test_layer_discovery_ignores_cache_and_data_only_directories(tmp_path, monkeypatch):
    for name in ('active/__init__.py', 'namespace/nested/module.py', 'flat.py',
                 'retired/__pycache__/old.pyc', 'resources/coefficients.csv'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(audit, 'PKG', tmp_path)
    assert audit.discover_units() == {'active', 'namespace', 'flat'}


@pytest.mark.parametrize('filename,source,edge,exit_code', [
    ('domain/probe.py', 'import sjtu_tpmshx.applications.gui.ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx.applications.gui.ui import theme as appearance', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'from ...applications.gui import ui as widgets', 'domain -> ui', 1),
    ('domain/probe.py', 'def load():\n    from ...applications.gui import ui', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx.applications.gui.ui import *', 'domain -> ui', 1),
    ('domain/probe.py', 'from ui.theme import get_theme', 'domain -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import tests as support', 'domain -> tests', 1),
    ('domain/probe.py', 'import io\nfrom io import StringIO', None, 0),
    ('domain/probe.py', 'from scipy import io', None, 0),
    ('models/probe.py', 'from sjtu_tpmshx.data_types import case_data', 'models -> domain', 0),
    ('models/probe.py', 'from sjtu_tpmshx import df_surrogate', 'models -> df_surrogate', 0),
    ('cpp_interface/full_3d_stage.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers -> df_surrogate (1x):', 0),
    ('cpp_interface/full_3d_stage.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE, predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from sjtu_tpmshx.physical_models.df_surrogate.predict import predict_K_cF',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('cpp_interface/full_3d_stage.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE\n'
     'from sjtu_tpmshx.physical_models.df_surrogate import predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('models/deep/probe.py', 'from ....applications.gui import ui', 'models -> ui', 1),
    ('models/__init__.py', 'from ...applications.gui import ui', 'models -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import io', 'domain -> io', 1),
    ('preprocess/probe.py', 'from sjtu_tpmshx.compute import compute', 'preprocess -> compute', 1),
    ('compute.py', 'from sjtu_tpmshx.preprocess.api import prepare_case', 'compute -> preprocess', 0),
])
def test_layer_audit_applies_policy_to_each_import_spelling(tmp_path, monkeypatch, capsys,
                                                           filename, source, edge, exit_code):
    package = tmp_path / 'sjtu_tpmshx'
    for unit in ('shared/domain', 'shared/models', 'applications/gui/ui',
                 'development/tests', 'shared/io', 'shared/df_surrogate', 'preprocess'):
        (package / unit).mkdir(parents=True, exist_ok=True)
        (package / unit / '__init__.py').touch()
    (package / 'compute.py').touch()
    if filename.split('/')[0] in ('domain', 'models'):
        filename = 'shared/' + filename
    path = package / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding='utf-8')
    monkeypatch.setattr(audit, 'PKG', package)
    monkeypatch.setattr(audit, 'REPO', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['audit_import_graph', '--fail-on-violations'])

    assert audit.main() == exit_code
    output = ' '.join(capsys.readouterr().out.split())
    assert ('0 edges' if edge is None else edge) in output


def test_logger_names_do_not_include_the_package_name():
    from sjtu_tpmshx.run_control.logutil import get_logger
    logger = get_logger('sjtu_tpmshx.solvers.api')
    assert logger.name == 'tpmshx.solvers.api'
    assert get_logger('solvers.api') is logger


def test_checkout_keeps_published_submodule_identity():
    subprocess.run([sys.executable, '-c',
                    "from pathlib import Path\nimport sjtu_tpmshx\n"
                    "assert Path(sjtu_tpmshx.__file__).resolve() == Path.cwd() / 'python/__init__.py'\n"
                    + PUBLIC_NAME_CHECK], cwd=REPO, check=True, timeout=60)


def test_published_workbook_module_help_uses_strict_cp1252_output(monkeypatch):
    monkeypatch.setenv('PYTHONIOENCODING', 'cp1252:strict')
    result = subprocess.run([sys.executable, '-m', 'sjtu_tpmshx.shared.df_surrogate.ingest_cfd_kappa', '--help'],
                            cwd=REPO, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
