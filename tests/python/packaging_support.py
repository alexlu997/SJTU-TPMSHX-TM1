"""Shared source and installed-package checks of published module names."""

PUBLIC_NAME_CHECK = """
import importlib
from importlib.resources import files
import sys

assert 'tm1.shared' not in sys.modules
from tm1.data_types.compute_config import ComputeConfig
from tm1.shared.domain.compute_config import ComputeConfig as published_config
assert published_config is ComputeConfig
importlib.invalidate_caches()
from tm1.shared.io import case_io
from tm1.shared.domain import module_ports, validate_geometry
from tm1.shared.configs import load_shanghai_baseline
assert case_io is importlib.import_module('tm1.file_io.case_io')
assert module_ports is importlib.import_module('tm1.run_control.module_ports')
assert validate_geometry is importlib.import_module('tm1.data_types.validator').validate_geometry
assert load_shanghai_baseline is importlib.import_module('tm1.model_configs').load_shanghai_baseline
assert files('tm1.shared.configs').joinpath('shanghai_baseline.json').is_file()
quick = importlib.import_module('tm1.solvers.backends.cpp.quick_design')
assert quick is importlib.import_module('tm1.solvers.quick_design')
assert callable(quick.run_case) and callable(quick.field_result)
quick_prepare = importlib.import_module('tm1.preprocess.quick_design')
quick_operations = ('prepare_quick_design', 'prepare_values', 'pressure_fractions')
for name in ('shared._native_quick_prepare', 'shared.models._native_quick_prepare'):
    published = importlib.import_module('tm1.' + name)
    if published is not quick_prepare or not all(callable(getattr(published, op)) for op in quick_operations):
        raise SystemExit(f'Quick preparation owner differs for {name}')
full_3d = importlib.import_module('tm1.solvers.backends.cpp.full_3d_stage')
assert full_3d is importlib.import_module('tm1.solvers.full_3d')
assert callable(full_3d.run_case) and callable(full_3d.capture_result)
before = importlib.import_module('tm1.solvers.backends.cpp.full_2d_stage')
current = importlib.import_module('tm1.solvers.full_2d')
assert before is current and callable(before.run_case) and callable(before.capture_result)
"""


def df_package_identity_check(shared_first: bool) -> str:
    canonical = "from tm1.physical_models.df_surrogate import predict\n"
    shared = "from tm1.shared import df_surrogate as shared_df\n"
    imports = shared + canonical if shared_first else canonical + shared
    return imports + '''
from importlib import import_module
from importlib.util import find_spec
import sys

from tm1.physical_models import df_surrogate as owner
assert shared_df.predict is owner.predict is predict
assert shared_df is owner
for name in ('predict', 'backend', 'experimental_correction', 'full_core_3cell_fixed_v2'):
    assert import_module('tm1.shared.df_surrogate.' + name) is import_module(owner.__name__ + '.' + name)
assert 'tm1.preprocess.offline.load_sco2_cfd' not in sys.modules
assert 'tm1.development.runs.cfd_asym.kappa_asym' not in sys.modules

from tm1.shared.df_surrogate import ingest_cfd_kappa as shared_ingest
from tm1.shared.df_surrogate import kappa_asym as shared_registry
from tm1.shared.df_surrogate.load_sco2_cfd import load_core as shared_core
from tm1.development.runs.cfd_asym import ingest_cfd_kappa, kappa_asym
from tm1.preprocess.offline import load_sco2_cfd
assert shared_ingest is ingest_cfd_kappa
assert shared_ingest.kappa_asym is kappa_asym
assert shared_registry is kappa_asym
assert shared_df.load_sco2_cfd is load_sco2_cfd
assert shared_core is load_sco2_cfd.load_core
assert not {'PySide6', 'CoolProp', 'sympy', 'skimage'}.intersection(sys.modules)
for name in ('ingest_cfd_kappa', 'kappa_asym', 'load_sco2_cfd'):
    assert find_spec('tm1.physical_models.df_surrogate.' + name) is None
'''
