"""The actual 3D physical grid and design can be prepared without a backend."""
import subprocess
import sys


def test_three_d_preparation_without_solver_import():
    result = subprocess.run([sys.executable, '-c', '''
import sys
import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.preprocess.three_d.preparation import prepare_case
config = ComputeConfig()
config.geometry.Lz_m = .03
config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
case = prepare_case(config, case_id='3d')
assert case.design_fields['eps_arr'].shape == (6, 5, 4)
assert case.design_fields['K_m2'].shape == (6, 5, 4)
assert case.parameters['prepared']['openings']['A']['inlet'].shape == (5, 4)
np.testing.assert_allclose(case.grid['z_edges'][-1], .03)
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
'''], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
