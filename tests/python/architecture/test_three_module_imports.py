"""Tests of import boundaries and the layer policy."""
import ast
from graphlib import CycleError
from pathlib import Path
import subprocess
import sys

import pytest

from tm1.development.runs.tools import audit_import_graph as audit
from tm1.development.runs.tools.audit_import_graph import LAYERS, import_targets, target_unit, unit_of

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


def forbidden_imports(source, forbidden, package='tm1'):
    violations = []
    for node in ast.walk(ast.parse(source)):
        for module in import_targets(node, package):
            if not module.startswith('tm1.'):
                continue
            owner = target_unit(module, LAYERS)
            application = module.startswith('tm1.applications') and owner != 'io'
            if owner in forbidden or ('applications' in forbidden and application):
                violations.append((node.lineno, module))
    return violations


def test_implementation_import_boundaries():
    failures, checked = [], set()
    for path in ROOT.rglob('*.py'):
        relative = path.relative_to(ROOT)
        owner = unit_of(path)
        if relative.parts[0] == 'cpp_interface':
            owner = 'backend'
        if owner in RULES:
            checked.add(owner)
            package = '.'.join(('tm1', *relative.parts[:-1]))
            for line, module in forbidden_imports(path.read_text(encoding='utf-8'), RULES[owner], package):
                failures.append(f'{relative}:{line}: {module}')
    assert checked == RULES.keys()
    assert not failures, '\n'.join(failures)


@pytest.mark.parametrize('module', [
    'solvers.api', 'solvers.full_2d', 'solvers.full_3d',
    'preprocess.two_d.preparation',
])
def test_checker_detects_imports_across_stage_boundaries(module):
    name = 'tm1.' + module
    source = f'def evaluate():\n    import {name}\n'
    assert (2, name) in forbidden_imports(source, RULES['postprocess'])


def test_checker_resolves_relative_imports_and_allows_shared_models():
    assert (1, 'tm1.solvers') in forbidden_imports(
        'from .. import solvers', ('solvers',), 'tm1.postprocess')
    assert not forbidden_imports('from tm1.physical_models.catalog import resolve_model', ('solvers',))


@pytest.mark.parametrize('source, forbidden', [
    ('run_control.run_warnings', 'cpp_interface'),
    ('cpp_interface.native_preparation', 'preprocess.api'),
    ('cpp_interface.native_preparation', 'preprocess.two_d.preparation'),
    ('cpp_interface.native_preparation', 'preprocess.three_d.preparation'),
    ('cpp_interface._native_preparation_3d', 'preprocess.three_d.preparation'),
    ('preprocess.two_d.preparation', 'preprocess.api'),
    ('preprocess.three_d.preparation', 'preprocess.api'),
    ('cpp_interface.full_2d_stage', 'solvers.execution_record'),
    ('cpp_interface.full_3d_stage', 'solvers.execution_record'),
    ('solvers.full_2d', 'solvers.execution_record'),
    ('solvers.full_3d', 'solvers.execution_record'),
])
def test_module_import_boundaries(source, forbidden):
    path = ROOT.joinpath(*source.split('.')).with_suffix('.py')
    package = 'tm1.' + source.rsplit('.', 1)[0]
    forbidden = 'tm1.' + forbidden
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        for module in import_targets(node, package):
            assert module != forbidden and not module.startswith(forbidden + '.'), f'{path}:{node.lineno}'


@pytest.mark.parametrize('owner', audit.CYCLE_OWNERS)
def test_implementation_imports_have_no_cycles(owner):
    modules = audit.owner_modules(owner)
    assert modules, owner
    audit.check_cycles(modules)


def test_configuration_and_native_properties_have_no_import_cycle():
    names = ('data_types.compute_config', 'file_io.config_io', 'file_io.text_file',
             'cpp_interface._native_df', 'cpp_interface._native_properties')
    audit.check_cycles({'tm1.' + name: ROOT.joinpath(*name.split('.')).with_suffix('.py')
                  for name in names})


def test_checker_detects_cycle_across_solver_directories(tmp_path):
    api, stage, host = ('tm1.solvers.api', 'tm1.cpp_interface.full_2d_stage',
                        'tm1.solvers.full_2d')
    imports = {(api, stage), (stage, host), (host, api)}
    modules = {name: tmp_path / f'{name.rsplit(".", 1)[1]}.py' for name in (api, stage, host)}
    for source, target in imports:
        modules[source].write_text(f'import {target}', encoding='utf-8')
    with pytest.raises(CycleError, match='cycle') as error:
        audit.check_cycles(modules)
    path = error.value.args[1]
    # The reported path follows the import direction.
    assert len(path) == 4 and set(zip(path, path[1:])) == imports


# Each probe runs in a new interpreter so that this module's imports cannot fill sys.modules.
@pytest.mark.parametrize('probe', [
    "import tm1.physical_models.df_surrogate.predict\n"
    "bad = {'tm1.physical_models.tpms_calc', 'tm1.physical_models.tpms_props'} & set(sys.modules)\n"
    "assert not bad, f'df_surrogate pulled kernel modules: {bad}'",
    "import tm1.physical_models.df_surrogate.predict, tm1.physical_models.df_surrogate.experimental_correction,"
    " tm1.physical_models.df_surrogate.full_core_3cell_fixed_v2, tm1.preprocess.api, tm1.solvers.api\n"
    "offline = ('tm1.preprocess.offline', 'tm1.development', 'CoolProp')\n"
    "assert not any(name.startswith(offline) for name in sys.modules)",
    "import tm1.physical_models.tpms_props\n"
    "bad = [m for m in sys.modules if m.startswith('tm1.physical_models.df_surrogate')"
    " or m.startswith('tm1.solvers') or m == 'tm1.physical_models.tpms_calc']\n"
    "if bad: raise SystemExit(f'tpms_props imported upper modules: {bad}')",
    "import tm1.preprocess.api, tm1.solvers.api\n"
    "import tm1.preprocess.two_d.preparation, tm1.preprocess.three_d.preparation\n"
    "bad = [m for m in sys.modules if m.startswith('tm1.applications.gui.controllers')]\n"
    "assert not bad, f'preparation pulled controllers: {bad}'",
    "import tm1.preprocess.preflight, tm1.applications.design.sensitivity\n"
    "assert 'PySide6' not in sys.modules",
    "from tm1.data_types.compute_config import ComputeConfig, ZoneInputConfig\n"
    "from tm1.data_types.validator import validate_geometry\n"
    "spec = dict(n_ctrl_x=1, n_ctrl_y=1, spline_order=1, symmetric_y=False,\n"
    "            x_decision=[7., .5], L_bounds=[4., 8.], t_bounds=[.3, .6])\n"
    "ComputeConfig(zones=ZoneInputConfig(enabled=True, axis='continuous', config=spec)).validate_static_inputs()\n"
    "validate_geometry(.1, .1, None, 7., .5)\n"
    "if 'tm1.physical_models' in sys.modules: raise SystemExit('Geometry validation imported physical models')",
], ids=['df-surrogate-below-kernel', 'runtime-without-offline', 'tpms-props-leaf',
        'preparation-without-controllers', 'preflight-and-sensitivity-without-qt', 'geometry-validation'])
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
    ('data_types/probe.py', 'import tm1.applications.gui.ui as widgets', 'domain -> ui', 1),
    ('data_types/probe.py', 'from tm1.applications.gui.ui import theme as appearance', 'domain -> ui', 1),
    ('data_types/probe.py', 'from tm1 import ui as widgets', 'domain -> ui', 1),
    ('data_types/probe.py', 'from ..applications.gui import ui as widgets', 'domain -> ui', 1),
    ('data_types/probe.py', 'def load():\n    from ..applications.gui import ui', 'domain -> ui', 1),
    ('data_types/probe.py', 'from tm1.applications.gui.ui import *', 'domain -> ui', 1),
    ('data_types/probe.py', 'from ui.theme import get_theme', 'domain -> ui', 1),
    ('data_types/probe.py', 'from tm1 import tests as support', 'domain -> tests', 1),
    ('data_types/probe.py', 'import io\nfrom io import StringIO', None, 0),
    ('data_types/probe.py', 'from scipy import io', None, 0),
    ('physical_models/probe.py', 'from tm1.data_types import case_data', 'models -> domain', 0),
    ('physical_models/probe.py', 'from tm1 import df_surrogate', 'models -> df_surrogate', 0),
    ('solvers/full_3d.py',
     'from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers -> df_surrogate (1x):', 0),
    ('solvers/full_3d.py',
     'from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE, predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from tm1.physical_models.df_surrogate.predict import predict_K_cF',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/api.py', 'from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('solvers/full_3d.py',
     'from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE\n'
     'from tm1.physical_models.df_surrogate import predict',
     'solvers (L1) -> df_surrogate (L2) (1x): UPWARD import', 1),
    ('cpp_interface/full_3d_stage.py',
     'from tm1.physical_models.df_surrogate import CFD_CAMPAIGN, CFD_SCOPE',
     'full 3D solve boundary -> tm1.physical_models.df_surrogate', 1),
    ('physical_models/deep/probe.py', 'from ...applications.gui import ui', 'models -> ui', 1),
    ('physical_models/__init__.py', 'from ..applications.gui import ui', 'models -> ui', 1),
    ('data_types/probe.py', 'from tm1 import io', 'domain -> io', 1),
    ('preprocess/probe.py', 'from tm1.compute import compute', 'preprocess -> compute', 1),
    ('compute.py', 'from tm1.preprocess.api import prepare_case', 'compute -> preprocess', 0),
    ('postprocess/api.py', 'def evaluate():\n    from ..cpp_interface import _native_result_stage as old',
     'independent result boundary -> tm1.cpp_interface._native_result_stage', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface._native_result_stage import evaluate_applicability',
     'independent result boundary -> tm1.cpp_interface._native_result_stage', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface.result_evaluation import _Evidence as raw',
     'independent result boundary -> tm1.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\nwire._Evidence()',
     'independent result boundary -> tm1.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation\n'
     'def source_ids(reports):\n    return [result_evaluation.source_result_id for result_evaluation in reports]',
     None, 0),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\n'
     'def reports():\n    return [wire.source_result_id for wire in wire._Evidence()]',
     'independent result boundary -> tm1.cpp_interface.result_evaluation._Evidence', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface import result_evaluation as wire\n'
     'def ids(reports):\n    wire = reports[0]\n    return (lambda wire: wire.source_result_id)(wire)',
     None, 0),
    ('cpp_interface/result_evaluation.py',
     'def assemble_record(provider=None):\n    from ..data_types import performance_result\n'
     '    records = performance_result if provider is None else provider\n'
     '    return records.PerformanceResult("new", "saved")',
     'result_evaluation.py:2: independent result boundary -> tm1.data_types.performance_result', 1),
    ('cpp_interface/result_evaluation.py',
     'from tm1 import data_types as dto\ndto.performance_result.PerformanceResult()',
     'independent result boundary -> tm1.data_types.performance_result', 1),
    ('cpp_interface/result_evaluation.py',
     'from itertools import starmap\nfrom ..data_types.performance_result import MetricValue\n'
     'def records(rows):\n    return tuple(starmap(MetricValue, rows))',
     'result_evaluation.py:2: independent result boundary -> tm1.data_types.performance_result.MetricValue', 1),
    ('cpp_interface/result_evaluation.py',
     'from ..data_types.performance_result import PerformanceResult as BuildReport\n'
     'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ._native_result_stage import Output as BuildReport\n'
     'BuildReport("new", "saved")',
     'result_evaluation.py:1: independent result boundary -> tm1.data_types.performance_result.PerformanceResult', 1),
    ('cpp_interface/_native_result_stage.py', 'import tm1.data_types.metric_spec as specs',
     'independent result boundary -> tm1.data_types.metric_spec', 1),
    ('cpp_interface/result_evaluation.py', 'from ..data_types.performance_result import *',
     'independent result boundary -> tm1.data_types.performance_result', 1),
    ('cpp_interface/_native_result_stage.py', 'from ..data_types.metric_spec import full_metric_version',
     'independent result boundary -> tm1.data_types.metric_spec.full_metric_version', 1),
    ('cpp_interface/result_evaluation.py', 'from ..data_types import MetricValue as Row',
     'independent result boundary -> tm1.data_types.MetricValue', 1),
    ('cpp_interface/_native_result_stage.py',
     'from ..data_types.metric_spec import MetricSpec\n'
     'def check(item: MetricSpec):\n    return isinstance(item, MetricSpec)',
     '_native_result_stage.py:1: independent result boundary -> tm1.data_types.metric_spec.MetricSpec', 1),
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
     'result_evaluation.py:4: independent result boundary -> tm1.data_types.metric_spec', 1),
    ('cpp_interface/_native_result_stage.py', 'from ..data_types import portable_data',
     'native_values -> domain', 0),
    ('cpp_interface/result_evaluation.py', 'from ..physical_models import fluid_props',
     'independent result boundary -> tm1.physical_models', 1),
    ('postprocess/evaluation.py', 'from ..cpp_interface.result_evaluation import query_result as run\nrun()', None, 0),
    ('postprocess/evaluation.py', 'import tm1.cpp_interface.result_evaluation as wire\nwire.query_result()', None, 0),
    ('postprocess/result_math.py', 'from ..cpp_interface import _native_result_checks', None, 0),
    ('cpp_interface/quick_design.py', 'from ..physical_models import design_fluids',
     'Quick solve boundary -> tm1.physical_models', 1),
    ('cpp_interface/quick_design.py', 'def replay():\n    from ..solvers import quick_design',
     'Quick solve boundary -> tm1.solvers', 1),
    ('cpp_interface/quick_design.py', 'from ..data_types.field_result import FieldResult as Result\nResult()',
     'Quick solve boundary -> tm1.data_types.field_result.FieldResult', 1),
    ('cpp_interface/quick_design.py', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
     '    from ..data_types.field_result import FieldResult', 'native_values -> domain', 0),
    ('solvers/quick_design.py', 'from ..cpp_interface import quick_design as wire\nwire._saved_v2()',
     'Quick solve boundary -> tm1.cpp_interface.quick_design._saved_v2', 1),
    ('solvers/quick_design.py', 'from ..cpp_interface.quick_design import QuickSolver', None, 0),
    ('cpp_interface/quick_design.py', 'from .full_2d_stage import run_case as full_solve',
     'Quick solve boundary -> tm1.cpp_interface.full_2d_stage', 1),
    ('cpp_interface/quick_design.py', 'from .. import cpp_interface as native\nnative.full_3d_stage.run_case()',
     'Quick solve boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('solvers/quick_design.py', 'from ..cpp_interface.quick_design import *\ncopy_ranges = closure_records',
     'Quick solve boundary -> tm1.cpp_interface.quick_design.*', 1),
    ('cpp_interface/quick_design.py', 'from .solver_library._stage_capture_abi import RangeRecordView\n'
     'from ._native_preparation_case import _QuickInputV2, _QuickPreparedV2', 'VIOLATIONS (0)', 0),
    ('cpp_interface/quick_preparation.py', 'from ..physical_models import co2_props as eos',
     'Quick preparation boundary -> tm1.physical_models', 1),
    ('cpp_interface/native_preparation.py', 'def cache():\n    from ..physical_models import sigmoid_field',
     'full preparation boundary -> tm1.physical_models', 1),
    ('cpp_interface/inlet_properties.py', 'from ..preprocess import preparation',
     'full preparation boundary -> tm1.preprocess', 1),
    ('cpp_interface/inlet_properties.py', 'from ..physical_models import tpms_calc',
     'full preparation boundary -> tm1.physical_models', 1),
    ('cpp_interface/native_preparation.py', 'from . import result_evaluation',
     'full preparation boundary -> tm1.cpp_interface.result_evaluation', 1),
    ('cpp_interface/preparation_host.py', 'from .. import cpp_interface as wire\nquery = wire.result_evaluation.query_result',
     'full preparation boundary -> tm1.cpp_interface.result_evaluation', 1),
    ('cpp_interface/preparation_host.py', 'from . import *',
     'full preparation boundary -> tm1.cpp_interface.*', 1),
    ('cpp_interface/inlet_properties.py', 'from ._native_preparation_case import *',
     'full preparation boundary -> tm1.cpp_interface._native_preparation_case.*', 1),
    ('cpp_interface/inlet_properties.py', 'from ._native_preparation_case import _InletQueryInput\n'
     'from ..run_control import run_warnings', 'VIOLATIONS (0)', 0),
    ('cpp_interface/inlet_properties.py', 'from typing import TYPE_CHECKING\n'
     'if TYPE_CHECKING:\n    from ..data_types.case_data import CaseData', 'VIOLATIONS (0)', 0),
    ('cpp_interface/native_preparation.py', 'from ..data_types import case_data as dto',
     'full preparation boundary -> tm1.data_types.case_data', 1),
    ('cpp_interface/preparation_host.py', 'from ..data_types.model_refs import ModelRef', 'VIOLATIONS (0)', 0),
    ('preprocess/two_d/preparation.py', 'from ...cpp_interface import native_preparation as native\nf = native._copy_case',
     'full preparation boundary -> tm1.cpp_interface.native_preparation._copy_case', 1),
    ('preprocess/two_d/preparation.py', 'from ...cpp_interface.native_preparation import *',
     'full preparation boundary -> tm1.cpp_interface.native_preparation.*', 1),
    ('preprocess/two_d/preparation.py', 'from ...cpp_interface.native_preparation import run_preparation',
     'VIOLATIONS (0)', 0),
    ('preprocess/three_d/preparation.py', 'from tm1.cpp_interface import _native_preparation_3d as three',
     'full 3D preparation boundary -> tm1.cpp_interface._native_preparation_3d', 1),
    ('preprocess/three_d/preparation.py', 'def pack():\n    from ...cpp_interface._native_preparation_case import _Options',
     'full 3D preparation boundary -> tm1.cpp_interface._native_preparation_case', 1),
    ('preprocess/three_d/preparation.py', 'from ...cpp_interface._native_values import GridPort',
     'full 3D preparation boundary -> tm1.cpp_interface._native_values', 1),
    ('preprocess/three_d/preparation.py', 'from ...cpp_interface import preparation_host as host\nhost._geometry_values(None)',
     'full 3D preparation boundary -> tm1.cpp_interface.preparation_host', 1),
    ('preprocess/three_d/preparation.py', 'from ... import cpp_interface as wire\nwire.preparation_host._geometry_values(None)',
     'full 3D preparation boundary -> tm1.cpp_interface.preparation_host._geometry_values', 1),
    ('preprocess/three_d/preparation.py', 'from ...cpp_interface import native_preparation as wire\nwire._copy_case(None)',
     'full 3D preparation boundary -> tm1.cpp_interface.native_preparation._copy_case', 1),
    ('preprocess/three_d/preparation.py', 'from ...cpp_interface.native_preparation import pack_input',
     'full 3D preparation boundary -> tm1.cpp_interface.native_preparation.pack_input', 1),
    ('preprocess/three_d/preparation.py', 'from ...cpp_interface.native_preparation import *',
     'full 3D preparation boundary -> tm1.cpp_interface.native_preparation.*', 1),
    ('preprocess/three_d/preparation.py',
     'from ...cpp_interface import native_preparation\n'
     'native_preparation.pack_volume_input()\nnative_preparation.run_volume_preparation()',
     'VIOLATIONS (0)', 0),
    ('preprocess/three_d/preparation.py',
     'from ...cpp_interface.native_preparation import pack_volume_input, run_volume_preparation',
     'VIOLATIONS (0)', 0),
    ('cpp_interface/_native_preparation_3d.py', 'from ..physical_models import tpms_props',
     'full preparation boundary -> tm1.physical_models', 1),
    ('cpp_interface/_native_preparation_3d.py', 'def build():\n    from ..data_types.case_data import CaseData',
     'full preparation boundary -> tm1.data_types.case_data.CaseData', 1),
    ('cpp_interface/_native_preparation_3d.py', 'from ..preprocess.three_d import preparation',
     'full preparation boundary -> tm1.preprocess', 1),
    ('cpp_interface/_native_preparation_3d.py',
     'from . import _native_preparation_case as native, preparation_host as host\n'
     'from ._native_values import GridPort, real_scalar\n'
     'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..data_types.case_data import CaseData',
     'VIOLATIONS (0)', 0),
    ('cpp_interface/_native_preparation_case.py', 'from ..preprocess.three_d import preparation',
     'full preparation boundary -> tm1.preprocess', 1),
    ('cpp_interface/_native_preparation_case.py', 'from ..data_types.case_data import CaseData',
     'full preparation boundary -> tm1.data_types.case_data.CaseData', 1),
    ('cpp_interface/_native_preparation_case.py',
     'from ._native_df import _Pressure\nfrom ._native_properties import _Failure\n'
     'from ._native_values import DoubleArray, Text',
     'VIOLATIONS (0)', 0),
    ('preprocess/api.py', 'from .. import cpp_interface as wire\nprepare = wire.native_preparation.run_preparation',
     'full preparation boundary -> tm1.cpp_interface.native_preparation', 1),
    ('preprocess/api.py', 'from ..cpp_interface import *',
     'full preparation boundary -> tm1.cpp_interface.*', 1),
    ('preprocess/api.py', 'from .two_d.preparation import prepare_case', 'VIOLATIONS (0)', 0),
    ('cpp_interface/quick_preparation.py', 'from ..physical_models.range_policy import assess_range',
     'Quick preparation boundary -> tm1.physical_models.range_policy', 1),
    ('cpp_interface/quick_preparation.py', 'from ..run_control import run_warnings', 'VIOLATIONS (0)', 0),
    ('cpp_interface/quick_preparation.py', 'def local():\n    from ..preprocess.quick_design import prepare_values',
     'Quick preparation boundary -> tm1.preprocess.quick_design', 1),
    ('cpp_interface/quick_preparation.py', 'from .full_2d_stage import run_case',
     'Quick preparation boundary -> tm1.cpp_interface.full_2d_stage', 1),
    ('cpp_interface/quick_preparation.py', 'from .preparation_host import observe_range',
     'Quick preparation boundary -> tm1.cpp_interface.preparation_host', 1),
    ('cpp_interface/quick_preparation.py', 'from ..data_types import case_data as inputs',
     'Quick preparation boundary -> tm1.data_types.case_data', 1),
    ('cpp_interface/quick_preparation.py', 'def refs():\n    from ..data_types.model_refs import ModelRef',
     'Quick preparation boundary -> tm1.data_types.model_refs.ModelRef', 1),
    ('cpp_interface/quick_preparation.py', 'from typing import TYPE_CHECKING\n'
     'if TYPE_CHECKING:\n    from ..data_types.case_data import CaseData', 'VIOLATIONS (0)', 0),
    ('preprocess/quick_design.py', 'from ..cpp_interface.quick_preparation import _Bindings',
     'Quick preparation boundary -> tm1.cpp_interface.quick_preparation._Bindings', 1),
    ('preprocess/quick_design.py', 'from ..cpp_interface.quick_preparation import run_preparation',
     'VIOLATIONS (0)', 0),
    ('applications/design/sizing.py', 'from ...cpp_interface import quick_preparation as wire',
     'Quick preparation boundary -> tm1.cpp_interface.quick_preparation', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..physical_models import nu_correlations',
     'full 3D solve boundary -> tm1.physical_models', 1),
    ('cpp_interface/full_3d_stage.py', 'def local():\n    from ..solvers import full_3d',
     'full 3D solve boundary -> tm1.solvers', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..data_types.field_result import FieldResult as Result\nResult()',
     'full 3D solve boundary -> tm1.data_types.field_result.FieldResult', 1),
    ('cpp_interface/full_3d_stage.py', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
     '    from ..data_types.field_result import FieldResult', 'native_values -> domain', 0),
    ('cpp_interface/full_3d_stage.py', 'from .full_2d_stage import run_case',
     'full 3D solve boundary -> tm1.cpp_interface.full_2d_stage', 1),
    ('cpp_interface/full_3d_stage.py', 'from . import result_evaluation',
     'full 3D solve boundary -> tm1.cpp_interface.result_evaluation', 1),
    ('cpp_interface/full_3d_stage.py', 'from . import *',
     'full 3D solve boundary -> tm1.cpp_interface.*', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..cpp_interface import *',
     'full 3D solve boundary -> tm1.cpp_interface.*', 1),
    ('cpp_interface/full_3d_stage.py', 'from ..postprocess import result_display',
     'full 3D solve boundary -> tm1.postprocess', 1),
    ('cpp_interface/full_3d_stage.py', 'from .run_state import NativeRun\n'
     'from .preparation_host import borrow_solver_mesh\n'
     'from .solver_library._full_3d_abi import _Input\n'
     'from .solver_library import stage_capture', 'VIOLATIONS (0)', 0),
    ('solvers/full_3d.py', 'from ..cpp_interface import full_3d_stage as wire\nwire._detach()',
     'full 3D solve boundary -> tm1.cpp_interface.full_3d_stage._detach', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface.full_3d_stage import *\nkeep = _copy',
     'full 3D solve boundary -> tm1.cpp_interface.full_3d_stage.*', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface import preparation_host',
     'full 3D solve boundary -> tm1.cpp_interface.preparation_host', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface import *',
     'full 3D solve boundary -> tm1.cpp_interface.*', 1),
    ('solvers/full_3d.py', 'from ..cpp_interface.full_3d_stage import open_library, borrow_mesh, '
     'require_saved_stage, execution_view_query, run_saved', None, 0),
    ('solvers/api.py', 'from ..cpp_interface.full_3d_stage import run_saved',
     'solver API boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from ..cpp_interface import full_3d_stage',
     'solver API boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from .. import cpp_interface\ncpp_interface.full_3d_stage.run_saved()',
     'solver API boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'import tm1.cpp_interface as ci\nci.full_3d_stage.run_saved()',
     'solver API boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('solvers/api.py', 'from ..cpp_interface import *',
     'solver API boundary -> tm1.cpp_interface.*', 1),
    ('solvers/api.py', 'from ..cpp_interface.full_2d_stage import run_stage',
     'solver API boundary -> tm1.cpp_interface.full_2d_stage', 1),
    ('solvers/api.py', 'from ..cpp_interface.quick_design import QuickSolver',
     'solver API boundary -> tm1.cpp_interface.quick_design', 1),
    ('solvers/api.py', 'from .full_2d import run_case as run_2d\n'
     'from .full_3d import run_case as run_3d\n'
     'from .quick_design import run_case as run_quick', 'VIOLATIONS (0)', 0),
    ('cpp_interface/full_2d_stage.py', 'def assemble():\n    from ..solvers.physical_ledger import ports_complete',
     'full 2D solve boundary -> tm1.solvers', 1),
    ('cpp_interface/full_2d_stage.py', 'from ..physical_models.envelope import ChokedFlowError',
     'full 2D solve boundary -> tm1.physical_models', 1),
    ('cpp_interface/full_2d_stage.py', 'from ..physical_models.zone_config import Zone',
     'full 2D solve boundary -> tm1.physical_models', 1),
    ('cpp_interface/full_2d_stage.py', 'from ..data_types.field_result import FieldResult',
     'full 2D solve boundary -> tm1.data_types.field_result.FieldResult', 1),
    ('cpp_interface/full_2d_stage.py', 'from ..data_types.case_data import CaseData',
     'full 2D solve boundary -> tm1.data_types.case_data.CaseData', 1),
    ('cpp_interface/full_2d_stage.py', 'import tm1.data_types as dt\ndt.FieldResult()',
     'full 2D solve boundary -> tm1.data_types.FieldResult', 1),
    ('cpp_interface/full_2d_stage.py', 'from .full_3d_stage import run_saved',
     'full 2D solve boundary -> tm1.cpp_interface.full_3d_stage', 1),
    ('cpp_interface/full_2d_stage.py', 'from . import *',
     'full 2D solve boundary -> tm1.cpp_interface.*', 1),
    ('cpp_interface/full_2d_stage.py', 'from ..run_control.cancellation import CancelledError\n'
     'from ..run_control.module_ports import RunControl\n'
     'from ..data_types.portable_data import mutable_data\n'
     'from .solver_library import stage_capture\n'
     'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
     '    from ..data_types.field_result import FieldResult', 'native_values -> domain', 0),
    ('solvers/full_2d.py', 'from ..cpp_interface import full_2d_stage as wire\nwire._Run()',
     'full 2D solve boundary -> tm1.cpp_interface.full_2d_stage._Run', 1),
    ('solvers/full_2d.py', 'from ..cpp_interface import full_2d_stage as wire\nwire._StageResult()',
     'full 2D solve boundary -> tm1.cpp_interface.full_2d_stage._StageResult', 1),
    ('solvers/full_2d.py', 'from ..cpp_interface.full_2d_stage import *',
     'full 2D solve boundary -> tm1.cpp_interface.full_2d_stage.*', 1),
    ('solvers/full_2d.py', 'from ..cpp_interface.solver_library import stage_capture',
     'full 2D solve boundary -> tm1.cpp_interface.solver_library', 1),
    ('solvers/full_2d.py', 'from ..cpp_interface import full_2d_stage\n'
     'full_2d_stage.StageDriver()\nfull_2d_stage.borrow_mesh()\nfull_2d_stage.stage_entries()\n'
     'full_2d_stage.check_experiment()\nfull_2d_stage.run_stage()\nfull_2d_stage.zone_temperatures()',
     None, 0),
    ('cpp_interface/run_state.py', 'from ..physical_models.fluid_props import WaterStateError',
     'native binding boundary -> tm1.physical_models', 1),
    ('cpp_interface/run_state.py', 'import ctypes\nimport numpy', None, 0),
    ('cpp_interface/preparation_host.py', 'from ._native_diagnostics import native_error', None, 0),
    ('cpp_interface/_native_diagnostics.py', 'from ..physical_models.fluid_props import WaterStateError',
     'native binding boundary -> tm1.physical_models', 1),
    ('cpp_interface/solver_library/stage_capture.py', 'from ...solvers import full_2d',
     'native binding boundary -> tm1.solvers', 1),
    ('cpp_interface/solver_library/stage_capture.py', 'from ...physical_models import tpms_props',
     'native binding boundary -> tm1.physical_models', 1),
    ('cpp_interface/solver_library/stage_capture.py', 'from ...data_types.field_result import FieldResult',
     'native binding boundary -> tm1.data_types.field_result.FieldResult', 1),
    ('cpp_interface/solver_library/stage_capture.py',
     'from ...run_control.run_warnings import RangeRecord', 'native_values -> domain', 0),
    ('cpp_interface/new_binding.py', 'from ..physical_models.range_policy import assess_range',
     'native binding boundary -> tm1.physical_models.range_policy', 1),
    ('cpp_interface/new_binding.py', 'from ..file_io.text_file import read_text',
     'native binding boundary -> tm1.file_io.text_file', 1),
    ('cpp_interface/new_binding.py', 'from ..applications import cli',
     'native binding boundary -> tm1.applications', 1),
    ('cpp_interface/new_binding.py', 'from ..compute import compute',
     'native binding boundary -> tm1.compute', 1),
    ('cpp_interface/new_binding.py', 'from .. import *',
     'native binding boundary -> tm1.*', 1),
    ('cpp_interface/new_binding.py', 'from ..data_types import *',
     'native binding boundary -> tm1.data_types.*', 1),
    ('cpp_interface/quick_design.py', 'from ..data_types import *',
     'Quick solve boundary -> tm1.data_types.*', 1),
    ('cpp_interface/new_binding.py', 'from ..data_types.case_data import CaseData',
     'native binding boundary -> tm1.data_types.case_data.CaseData', 1),
    ('cpp_interface/new_binding.py', 'from ..data_types.performance_result import PerformanceResult',
     'native binding boundary -> tm1.data_types.performance_result.PerformanceResult', 1),
    ('cpp_interface/new_binding.py', 'from ..data_types.model_refs import ModelRef',
     'native binding boundary -> tm1.data_types.model_refs.ModelRef', 1),
    ('cpp_interface/new_binding.py', 'from ..model_configs import model_parameters\n'
     'from ..run_control.run_warnings import RangeRecord', 'native_values -> domain', 0),
    ('cpp_interface/solver_library/new_helper.py', 'from ...preprocess import api',
     'native binding boundary -> tm1.preprocess', 1),
    ('cpp_interface/solver_library/new_helper.py', 'from ...postprocess import api',
     'native binding boundary -> tm1.postprocess', 1),
    ('cpp_interface/solver_library/new_helper.py', 'from ...data_types.metric_spec import MetricSpec',
     'native binding boundary -> tm1.data_types.metric_spec.MetricSpec', 1),
    ('cpp_interface/quick_design.py', 'from ..data_types.case_data import CaseData',
     'Quick solve boundary -> tm1.data_types.case_data.CaseData', 1),
    ('cpp_interface/preparation_host.py', 'from ..data_types.field_result import FieldResult',
     'full preparation boundary -> tm1.data_types.field_result.FieldResult', 1),
    ('run_control/probe.py', 'from tm1.physical_models import range_policy', None, 0),
    ('run_control/probe.py', 'from tm1.physical_models import fluid_props',
     'domain (L0) -> models (L0.5) (1x): UPWARD import', 1),
    ('run_control/probe.py', 'import tm1.physical_models',
     'domain (L0) -> models (L0.5) (1x): UPWARD import', 1),
])
def test_layer_audit_applies_policy_to_each_import_spelling(tmp_path, monkeypatch, capsys,
                                                           filename, source, edge, exit_code):
    package = tmp_path / 'tm1'
    for unit in ('data_types', 'physical_models', 'applications/gui/ui',
                 'development/tests', 'file_io', 'physical_models/df_surrogate', 'preprocess'):
        (package / unit).mkdir(parents=True, exist_ok=True)
        (package / unit / '__init__.py').touch()
    (package / 'compute.py').touch()
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
    from tm1.run_control.logutil import get_logger
    logger = get_logger('tm1.solvers.api')
    assert logger.name == 'tm1.solvers.api'
    assert get_logger('solvers.api') is logger


def test_published_workbook_module_help_uses_strict_cp1252_output(monkeypatch):
    monkeypatch.setenv('PYTHONIOENCODING', 'cp1252:strict')
    result = subprocess.run([sys.executable, '-m', 'tm1.development.runs.cfd_asym.ingest_cfd_kappa', '--help'],
                            cwd=REPO, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
