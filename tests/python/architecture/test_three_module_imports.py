"""Check import boundaries, layer policy, and published module identity."""
import ast
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
import subprocess
import sys

import pytest

from sjtu_tpmshx.development.runs.tools import audit_import_graph as audit
from sjtu_tpmshx.development.runs.tools.audit_import_graph import LAYERS, import_targets, target_unit, unit_of
from tests.python.packaging_support import PUBLIC_NAME_CHECK, df_package_identity_check

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
    ('solvers.full_3d', 'solvers.execution_record'),
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
    "import sjtu_tpmshx.physical_models.df_surrogate.predict, sjtu_tpmshx.preprocess.api, sjtu_tpmshx.solvers.api\n"
    "offline = ('sjtu_tpmshx.preprocess.offline', 'sjtu_tpmshx.development', 'CoolProp')\n"
    "assert not any(name.startswith(offline) for name in sys.modules)",
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
], ids=['df-surrogate-below-kernel', 'runtime-without-offline', 'tpms-props-leaf',
        'preparation-without-controllers', 'geometry-validation'])
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
    ('solvers/full_3d.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers -> df_surrogate (1x):', 0),
    ('solvers/full_3d.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE, predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from sjtu_tpmshx.physical_models.df_surrogate.predict import predict_K_cF',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/full_3d.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE\n'
     'from sjtu_tpmshx.physical_models.df_surrogate import predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('cpp_interface/full_3d_stage.py',
     'from sjtu_tpmshx.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'full 3D solve boundary -> sjtu_tpmshx.physical_models.df_surrogate', 1),
    ('models/deep/probe.py', 'from ....applications.gui import ui', 'models -> ui', 1),
    ('models/__init__.py', 'from ...applications.gui import ui', 'models -> ui', 1),
    ('domain/probe.py', 'from sjtu_tpmshx import io', 'domain -> io', 1),
    ('preprocess/probe.py', 'from sjtu_tpmshx.compute import compute', 'preprocess -> compute', 1),
    ('compute.py', 'from sjtu_tpmshx.preprocess.api import prepare_case', 'compute -> preprocess', 0),
    ('postprocess/api.py', 'def evaluate():\n    from ..cpp_interface import _native_result_stage as old',
     'independent result boundary -> sjtu_tpmshx.cpp_interface._native_result_stage', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface._native_result_stage import evaluate_applicability',
     'independent result boundary -> sjtu_tpmshx.cpp_interface._native_result_stage', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface.result_evaluation import _Evidence as raw',
     'independent result boundary -> sjtu_tpmshx.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\nwire._Evidence()',
     'independent result boundary -> sjtu_tpmshx.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation\n'
     'def source_ids(reports):\n    return [result_evaluation.source_result_id for result_evaluation in reports]',
     None, 0),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\n'
     'def reports():\n    return [wire.source_result_id for wire in wire._Evidence()]',
     'independent result boundary -> sjtu_tpmshx.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\n'
     'def ids(reports):\n    wire = reports[0]\n    return (lambda wire: wire.source_result_id)(wire)',
     None, 0),
    ('postprocess/api.py', 'from sjtu_tpmshx.shared import _native_result_stage',
     'independent result boundary -> sjtu_tpmshx.shared._native_result_stage', 1),
    ('cpp_interface/result_evaluation.py',
     'def assemble_record(provider=None):\n    from ..data_types import performance_result\n'
     '    records = performance_result if provider is None else provider\n'
     '    return records.PerformanceResult("new", "saved")',
     'result_evaluation.py:2: independent result boundary -> sjtu_tpmshx.data_types.performance_result', 1),
    ('cpp_interface/result_evaluation.py',
     'from sjtu_tpmshx import data_types as dto\ndto.performance_result.PerformanceResult()',
     'independent result boundary -> sjtu_tpmshx.data_types.performance_result', 1),
    ('cpp_interface/result_evaluation.py',
     'from itertools import starmap\nfrom ..data_types.performance_result import MetricValue\n'
     'def records(rows):\n    return tuple(starmap(MetricValue, rows))',
     'result_evaluation.py:2: independent result boundary -> sjtu_tpmshx.data_types.performance_result.MetricValue', 1),
    ('cpp_interface/result_evaluation.py',
     'from ..data_types.performance_result import PerformanceResult as BuildReport\n'
     'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ._native_result_stage import Output as BuildReport\n'
     'BuildReport("new", "saved")',
     'result_evaluation.py:1: independent result boundary -> sjtu_tpmshx.data_types.performance_result.PerformanceResult', 1),
    ('cpp_interface/_native_result_stage.py', 'import sjtu_tpmshx.data_types.metric_spec as specs',
     'independent result boundary -> sjtu_tpmshx.data_types.metric_spec', 1),
    ('cpp_interface/result_evaluation.py', 'from ..shared.domain.performance_result import *',
     'independent result boundary -> sjtu_tpmshx.shared.domain.performance_result', 1),
    ('cpp_interface/_native_result_stage.py', 'from ..data_types.metric_spec import full_metric_version',
     'independent result boundary -> sjtu_tpmshx.data_types.metric_spec.full_metric_version', 1),
    ('cpp_interface/result_evaluation.py', 'from ..data_types import MetricValue as Row',
     'independent result boundary -> sjtu_tpmshx.data_types.MetricValue', 1),
    ('cpp_interface/_native_result_stage.py',
     'from ..data_types.metric_spec import MetricSpec\n'
     'def check(item: MetricSpec):\n    return isinstance(item, MetricSpec)',
     '_native_result_stage.py:1: independent result boundary -> sjtu_tpmshx.data_types.metric_spec.MetricSpec', 1),
    ('cpp_interface/_native_result_stage.py',
     'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..data_types.metric_spec import MetricSpec\n'
     'def pack(spec: "MetricSpec"):\n    return spec.name',
     'native_values -> domain', 0),
    ('cpp_interface/result_evaluation.py',
     'import typing as t\nif t.TYPE_CHECKING:\n    from ..data_types import performance_result as output_types\n'
     'else:\n    from ._native_result_stage import Output\nOutput()',
     'native_values -> domain', 0),
    ('cpp_interface/result_evaluation.py',
     'from typing import TYPE_CHECKING as checking\n'
     'def pack(checking):\n    if checking:\n        from ..data_types import metric_spec as local',
     'result_evaluation.py:4: independent result boundary -> sjtu_tpmshx.data_types.metric_spec', 1),
    ('cpp_interface/_native_result_stage.py', 'from ..data_types import portable_data',
     'native_values -> domain', 0),
    ('cpp_interface/result_evaluation.py', 'from ..physical_models import fluid_props',
     'independent result boundary -> sjtu_tpmshx.physical_models', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface.result_evaluation import query_result as run\nrun()', None, 0),
    ('postprocess/evaluation.py', 'import sjtu_tpmshx.cpp_interface.result_evaluation as wire\nwire.query_result()', None, 0),
    ('postprocess/result_math.py', 'from ..cpp_interface import _native_result_checks', None, 0),
    ('cpp_interface/quick_design.py', 'from ..physical_models import design_fluids',
     'Quick solve boundary -> sjtu_tpmshx.physical_models', 1),
    ('cpp_interface/quick_design.py', 'def replay():\n    from ..solvers import quick_design',
     'Quick solve boundary -> sjtu_tpmshx.solvers', 1),
    ('cpp_interface/quick_design.py', 'from ..data_types.field_result import FieldResult as Result\nResult()',
     'Quick solve boundary -> sjtu_tpmshx.data_types.field_result.FieldResult', 1),
    ('cpp_interface/quick_design.py', 'from ..shared import domain\ndomain.field_result.FieldResult()',
     'Quick solve boundary -> sjtu_tpmshx.shared.domain.field_result', 1),
    ('cpp_interface/quick_design.py', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
     '    from ..data_types.field_result import FieldResult', 'solvers -> domain', 0),
    ('solvers/quick_design.py', 'from ..cpp_interface import quick_design as wire\nwire._saved_v2()',
     'Quick solve boundary -> sjtu_tpmshx.cpp_interface.quick_design._saved_v2', 1),
    ('solvers/quick_design.py', 'from ..cpp_interface.quick_design import QuickSolver', None, 0),
    ('cpp_interface/quick_design.py', 'from .full_2d_stage import run_case as full_solve',
     'Quick solve boundary -> sjtu_tpmshx.cpp_interface.full_2d_stage', 1),
    ('solvers/quick_design.py', 'from .backends.cpp.full_2d_stage import run_case as full_solve',
     'Quick solve boundary -> sjtu_tpmshx.solvers.backends.cpp.full_2d_stage', 1),
    ('cpp_interface/quick_design.py', 'from .. import cpp_interface as native\nnative.full_3d_stage.run_case()',
     'Quick solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage', 1),
    ('solvers/quick_design.py', 'from .backends import cpp\ncpp.full_3d_stage.run_case()',
     'Quick solve boundary -> sjtu_tpmshx.solvers.backends.cpp.full_3d_stage', 1),
    ('solvers/quick_design.py', 'from ..cpp_interface.quick_design import *\ncopy_ranges = closure_records',
     'Quick solve boundary -> sjtu_tpmshx.cpp_interface.quick_design.*', 1),
    ('cpp_interface/quick_design.py', 'from ..shared import _native_quick_prepare',
     'Quick solve boundary -> sjtu_tpmshx.shared._native_quick_prepare', 1),
    ('cpp_interface/quick_design.py', 'from .solver_library._stage_capture_abi import RangeRecordView\n'
     'from ._native_preparation_case import _QuickInputV2, _QuickPreparedV2', 'VIOLATIONS (0)', 0),
    ('cpp_interface/quick_preparation.py', 'from ..physical_models import co2_props as eos',
     'Quick preparation boundary -> sjtu_tpmshx.physical_models', 1),
    ('cpp_interface/quick_preparation.py', 'from ..physical_models.range_policy import assess_range',
     'Quick preparation boundary -> sjtu_tpmshx.physical_models.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from sjtu_tpmshx.shared.domain.range_policy import assess_range',
     'Quick preparation boundary -> sjtu_tpmshx.shared.domain.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from sjtu_tpmshx.data_types.range_policy import assess_range',
     'Quick preparation boundary -> sjtu_tpmshx.data_types.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from ..data_types import range_policy as limits',
     'Quick preparation boundary -> sjtu_tpmshx.data_types.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from ..shared import domain\nassess = domain.range_policy.assess_range',
     'Quick preparation boundary -> sjtu_tpmshx.shared.domain.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from ..shared.domain import run_warnings', 'VIOLATIONS (0)', 0),
    ('cpp_interface/quick_preparation.py', 'def local():\n    from ..preprocess.quick_design import prepare_values',
     'Quick preparation boundary -> sjtu_tpmshx.preprocess.quick_design', 1),
    ('cpp_interface/quick_preparation.py', 'from .full_2d_stage import run_case',
     'Quick preparation boundary -> sjtu_tpmshx.cpp_interface.full_2d_stage', 1),
    ('cpp_interface/quick_preparation.py', 'from .preparation_host import observe_range',
     'Quick preparation boundary -> sjtu_tpmshx.cpp_interface.preparation_host', 1),
    ('cpp_interface/quick_preparation.py', 'from ..data_types import case_data as inputs',
     'Quick preparation boundary -> sjtu_tpmshx.data_types.case_data', 1),
    ('cpp_interface/quick_preparation.py', 'def refs():\n    from ..shared.domain.model_refs import ModelRef',
     'Quick preparation boundary -> sjtu_tpmshx.shared.domain.model_refs.ModelRef', 1),
    ('cpp_interface/quick_preparation.py', 'from typing import TYPE_CHECKING\n'
     'if TYPE_CHECKING:\n    from ..data_types.case_data import CaseData', 'VIOLATIONS (0)', 0),
    ('preprocess/quick_design.py', 'from ..cpp_interface.quick_preparation import _Bindings',
     'Quick preparation boundary -> sjtu_tpmshx.cpp_interface.quick_preparation._Bindings', 1),
    ('preprocess/quick_design.py', 'from ..cpp_interface.quick_preparation import run_preparation',
     'VIOLATIONS (0)', 0),
    ('preprocess/api.py', 'from ..cpp_interface._native_quick_prepare import prepare_quick_design',
     'Quick preparation boundary -> sjtu_tpmshx.cpp_interface._native_quick_prepare', 1),
    ('applications/design/sizing.py', 'from ...shared.models._native_quick_prepare import pressure_fractions',
     'Quick preparation boundary -> sjtu_tpmshx.shared.models._native_quick_prepare', 1),
    ('applications/design/sizing.py', 'from ...cpp_interface import quick_preparation as wire',
     'Quick preparation boundary -> sjtu_tpmshx.cpp_interface.quick_preparation', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..physical_models import nu_correlations',
     'full 3D solve boundary -> sjtu_tpmshx.physical_models', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..shared.domain.range_policy import assess_range',
     'full 3D solve boundary -> sjtu_tpmshx.shared.domain.range_policy', 1),
    ('cpp_interface/full_3d_stage.py', 'def local():\n    from ..solvers import full_3d',
     'full 3D solve boundary -> sjtu_tpmshx.solvers', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..solvers.backends.cpp.full_3d_stage import run_case',
     'full 3D solve boundary -> sjtu_tpmshx.solvers.backends.cpp.full_3d_stage', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..data_types.field_result import FieldResult as Result\nResult()',
     'full 3D solve boundary -> sjtu_tpmshx.data_types.field_result.FieldResult', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..shared import domain\ndomain.field_result.FieldResult()',
     'full 3D solve boundary -> sjtu_tpmshx.shared.domain.field_result', 1),
    ('cpp_interface/full_3d_stage.py', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
     '    from ..data_types.field_result import FieldResult', 'solvers -> domain', 0),
    ('cpp_interface/full_3d_stage.py', 'from .full_2d_stage import run_case',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_2d_stage', 1),
    ('cpp_interface/full_3d_stage.py', 'from . import result_evaluation',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.result_evaluation', 1),
    ('cpp_interface/full_3d_stage.py', 'from . import *',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.*', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..cpp_interface import *',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.*', 1),
    ('cpp_interface/full_3d_stage.py', 'from sjtu_tpmshx.shared import result_display',
     'full 3D solve boundary -> sjtu_tpmshx.shared.result_display', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..shared import result_math',
     'full 3D solve boundary -> sjtu_tpmshx.shared.result_math', 1),
    ('cpp_interface/full_3d_stage.py', 'import sjtu_tpmshx.shared as shared\nshared.result_math.pressure_ratio',
     'full 3D solve boundary -> sjtu_tpmshx.shared.result_math', 1),
    ('cpp_interface/full_3d_stage.py', 'from .run_state import NativeRun\n'
     'from .preparation_host import borrow_solver_mesh\n'
     'from .solver_library._full_3d_abi import _Input\n'
     'from ._native_result_stage import link_execution', 'VIOLATIONS (0)', 0),
    ('solvers/full_3d.py', 'from ..cpp_interface import full_3d_stage as wire\nwire._detach()',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage._detach', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface.full_3d_stage import *\nkeep = _copy',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage.*', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface import preparation_host',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.preparation_host', 1),
    ('solvers/full_3d.py', 'from sjtu_tpmshx.physical_models import _native_result_stage',
     'full 3D solve boundary -> sjtu_tpmshx.physical_models._native_result_stage', 1),
    ('solvers/full_3d.py', 'import sjtu_tpmshx.physical_models as models\nmodels._native_result_stage.link_execution()',
     'full 3D solve boundary -> sjtu_tpmshx.physical_models._native_result_stage', 1),
    ('solvers/full_3d.py', 'from .backends.cpp import *',
     'full 3D solve boundary -> sjtu_tpmshx.solvers.backends.cpp.*', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface import *',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.*', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface.full_3d_stage import open_library, borrow_mesh, '
     'require_saved_stage, execution_view_query, run_saved, link_execution', None, 0),
    ('solvers/api.py', 'from ..cpp_interface.full_3d_stage import run_saved',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from ..cpp_interface import full_3d_stage',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from .. import cpp_interface\ncpp_interface.full_3d_stage.run_saved()',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'import sjtu_tpmshx.cpp_interface as ci\nci.full_3d_stage.run_saved()',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from ..cpp_interface import *',
     'full 3D solve boundary -> sjtu_tpmshx.cpp_interface.*', 1),
    ('solvers/api.py', 'from sjtu_tpmshx.cpp_interface.full_2d_stage import run_case as run_2d\n'
     'from .full_3d import run_case as run_3d', 'VIOLATIONS (0)', 0),
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


@pytest.mark.parametrize('shared_first', [False, True], ids=['canonical-first', 'shared-first'])
def test_checkout_keeps_df_package_identity(shared_first):
    subprocess.run([sys.executable, '-c', df_package_identity_check(shared_first)],
                   cwd=REPO, check=True, timeout=60)


def test_published_sco2_reader_runs_in_a_fresh_interpreter():
    subprocess.run([sys.executable, '-m', 'sjtu_tpmshx.shared.df_surrogate.load_sco2_cfd'],
                   cwd=REPO, check=True, timeout=60)


@pytest.mark.parametrize('module', [
    'sjtu_tpmshx.shared.df_surrogate.ingest_cfd_kappa',
    'sjtu_tpmshx.development.runs.cfd_asym.ingest_cfd_kappa',
])
def test_published_workbook_module_help_uses_strict_cp1252_output(monkeypatch, module):
    monkeypatch.setenv('PYTHONIOENCODING', 'cp1252:strict')
    result = subprocess.run([sys.executable, '-m', module, '--help'],
                            cwd=REPO, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
