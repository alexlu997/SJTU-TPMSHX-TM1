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
for dimension in (2, 3):
    leaf = f'full_{dimension}d'
    driver = f'NativeFull{dimension}DDriver'
    before = importlib.import_module('sjtu_tpmshx.solvers.backends.cpp.' + leaf)
    current = importlib.import_module('sjtu_tpmshx.cpp_interface.solver_library.' + leaf)
    assert before is current and getattr(before, driver) is getattr(current, driver)
"""
