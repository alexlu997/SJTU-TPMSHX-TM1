"""True preparation uses no active numerical backend or runtime object."""
import subprocess
import sys


def test_prepare_refined_and_partial_cases_in_clean_process():
    code = '''
import sys
import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, PartialBCConfig
from sjtu_tpmshx.preprocess.two_d.preparation import prepare_case
config = ComputeConfig()
config.solver.Nx, config.solver.Ny = 20, 40
case = prepare_case(config, case_id="full-port")
assert len(case.grid["dx"]) == 36 and len(case.grid["dy"]) == 56
np.testing.assert_allclose(case.grid["x_edges"][-1], config.geometry.L_dom_m)
np.testing.assert_allclose(case.grid["y_edges"][-1], config.geometry.H_dom_m)
assert case.parameters["L_cell_m"] == config.geometry.L_cell_mm * 1e-3
assert len(case.model_refs) == 4
assert case.design_fields["eps_arr"].shape == (36, 56)
np.testing.assert_allclose(np.dot(case.grid["dy"], case.parameters["boundary_openings"]["A"]["in_geom_frac"]), config.geometry.H_dom_m, rtol=1e-13)
config.bc_A = PartialBCConfig(dir=0, in_ctr=0.02, in_w=0.01, out_ctr=0.02, out_w=0.01)
partial = prepare_case(config, case_id="partial-port")
assert len(partial.grid["dx"]) == 20 and len(partial.grid["dy"]) == 40
np.testing.assert_allclose(np.dot(partial.grid["dy"], partial.parameters["boundary_openings"]["A"]["in_geom_frac"]), 0.01)
assert np.min(np.abs(partial.grid["y_edges"] - 0.015)) < 1e-14
assert np.min(np.abs(partial.grid["y_edges"] - 0.025)) < 1e-14
try:
    case.grid["dx"].setflags(write=True)
except ValueError:
    pass
else:
    raise AssertionError("prepared grid can be mutated")
for prefix in ("sjtu_tpmshx.solvers", "sjtu_tpmshx.pipelines", "numba", "PySide6"):
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), prefix
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_zoned_preparation_keeps_si_design_and_detaches_input():
    from dataclasses import asdict
    import numpy as np
    from sjtu_tpmshx.domain.compute_config import ComputeConfig
    from sjtu_tpmshx.models.zone_config import ZoneConfig
    from sjtu_tpmshx.preprocess.two_d.preparation import prepare_case
    config = ComputeConfig()
    config.solver.Nx = config.solver.Ny = 10
    config.zones.enabled = True
    config.zones.axis = 'y'
    config.zones.config = asdict(ZoneConfig.single_zone(6.0, 0.5, 'Gyroid', 16.0))
    case = prepare_case(config, case_id='zoned')
    assert case.design_fields['eps_arr'].shape == (10, 10)
    assert case.design_fields['zone_params'][0]['L_m'] == 0.006
    config.zones.config['zones'][0]['L_mm'] = 7.0
    assert case.parameters['zone_config']['zones'][0]['L_m'] == 0.006
    assert np.all(case.design_fields['zone_id'] == 0)


def test_prepared_inlet_warning_keeps_side_and_stage():
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig
    from sjtu_tpmshx.preprocess.api import prepare_case
    config = ComputeConfig(fluid_B=FluidConfig(type='water', u_mps=.001,
                                               T_in_K=300., P_in_Pa=101325.))
    config.solver.Nx = config.solver.Ny = 10
    config.extrap.allow = True
    case = prepare_case(config, case_id='inlet-warning')
    messages = [w for w in case.metadata['warnings'] if '[water Nu extrap]' in w]
    assert messages
    assert all('side=B, stage=inlet, layout=scalar' in w for w in messages)
