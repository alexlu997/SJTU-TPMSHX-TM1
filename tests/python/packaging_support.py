"""Shared source and installed-package checks of published module names."""

PUBLIC_NAME_CHECK = """
import importlib
from importlib.resources import files
import sys

assert 'sjtu_tpmshx.shared' not in sys.modules
from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig as published_config
assert published_config is ComputeConfig
importlib.invalidate_caches()
from sjtu_tpmshx.shared.io import case_io
from sjtu_tpmshx.shared.domain import module_ports, validate_geometry
from sjtu_tpmshx.shared.configs import load_shanghai_baseline
assert case_io is importlib.import_module('sjtu_tpmshx.file_io.case_io')
assert module_ports is importlib.import_module('sjtu_tpmshx.run_control.module_ports')
assert validate_geometry is importlib.import_module('sjtu_tpmshx.data_types.validator').validate_geometry
assert load_shanghai_baseline is importlib.import_module('sjtu_tpmshx.model_configs').load_shanghai_baseline
assert files('sjtu_tpmshx.shared.configs').joinpath('shanghai_baseline.json').is_file()
quick = importlib.import_module('sjtu_tpmshx.solvers.backends.cpp.quick_design')
assert quick is importlib.import_module('sjtu_tpmshx.solvers.quick_design')
assert callable(quick.run_case) and callable(quick.field_result)
quick_prepare = importlib.import_module('sjtu_tpmshx.preprocess.quick_design')
quick_operations = ('prepare_quick_design', 'prepare_values', 'pressure_fractions')
for name in ('shared._native_quick_prepare', 'shared.models._native_quick_prepare'):
    published = importlib.import_module('sjtu_tpmshx.' + name)
    if published is not quick_prepare or not all(callable(getattr(published, op)) for op in quick_operations):
        raise SystemExit(f'Quick preparation owner differs for {name}')
for dimension in (2, 3):
    leaf = f'full_{dimension}d_stage'
    before = importlib.import_module('sjtu_tpmshx.solvers.backends.cpp.' + leaf)
    current = importlib.import_module('sjtu_tpmshx.cpp_interface.' + leaf)
    assert before is current and before.run_case is current.run_case
"""


def df_package_identity_check(shared_first: bool) -> str:
    canonical = "from sjtu_tpmshx.physical_models.df_surrogate import predict\n"
    shared = "from sjtu_tpmshx.shared import df_surrogate as shared_df\n"
    imports = shared + canonical if shared_first else canonical + shared
    return imports + '''
from importlib import import_module
from importlib.util import find_spec
import sys

from sjtu_tpmshx.physical_models import df_surrogate as owner
assert shared_df.predict is owner.predict is predict
assert shared_df is owner
for name in ('predict', 'backend', 'experimental_correction', 'full_core_3cell_fixed_v2'):
    assert import_module('sjtu_tpmshx.shared.df_surrogate.' + name) is import_module(owner.__name__ + '.' + name)
assert 'sjtu_tpmshx.preprocess.offline.load_sco2_cfd' not in sys.modules
assert 'sjtu_tpmshx.development.runs.cfd_asym.kappa_asym' not in sys.modules

from sjtu_tpmshx.shared.df_surrogate import ingest_cfd_kappa as shared_ingest
from sjtu_tpmshx.shared.df_surrogate import kappa_asym as shared_registry
from sjtu_tpmshx.shared.df_surrogate.load_sco2_cfd import load_core as shared_core
from sjtu_tpmshx.development.runs.cfd_asym import ingest_cfd_kappa, kappa_asym
from sjtu_tpmshx.preprocess.offline import load_sco2_cfd
assert shared_ingest is ingest_cfd_kappa
assert shared_ingest.kappa_asym is kappa_asym
assert shared_registry is kappa_asym
assert shared_df.load_sco2_cfd is load_sco2_cfd
assert shared_core is load_sco2_cfd.load_core
assert not {'PySide6', 'CoolProp', 'sympy', 'skimage'}.intersection(sys.modules)
for name in ('ingest_cfd_kappa', 'kappa_asym', 'load_sco2_cfd'):
    assert find_spec('sjtu_tpmshx.physical_models.df_surrogate.' + name) is None
'''
