"""Real public-result mapping retains the GUI/export and diagnostic contract."""
from dataclasses import replace
import importlib

import numpy as np
import pytest

from sjtu_tpmshx.controllers.module_adapter import to_compute_result
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, SolverConfig,
    PartialBCConfig, ExtrapPolicy, FeatureFlags,
)
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config
from sjtu_tpmshx.tests.integration_tm1.test_public_api import assert_slots


def _small_air_air_cfg():
    """Tiny air-air cross-flow case (8x8x4) — fast, exercises both fluids."""
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=8.0, T_in_K=420.0, P_in_Pa=150000.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=320.0, P_in_Pa=101325.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.10, H_dom_m=0.042,
                                Lz_m=0.030),
        solver=SolverConfig(Nx=8, Ny=8, Nz=4),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        bc_B=PartialBCConfig(dir=3, in_ctr=0.021, in_w=0.042,
                             out_ctr=0.021, out_w=0.042),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(wall_refine_3d=False),
    )


@pytest.fixture(scope='module', params=[2, 3])
def native_result(request):
    dimension = request.param
    config = baseline_config() if dimension == 2 else _small_air_air_cfg()
    module = importlib.import_module(
        'sjtu_tpmshx.solvers.backends.python.'
        + ('two_d' if dimension == 2 else 'three_d') + '.result_capture')
    captured = []
    capture = module.capture_result
    def record(*args):
        captured.append(args[1] if dimension == 2 else args[3])
        return capture(*args)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, 'capture_result', record)
        case = prepare_case(config, case_id=f'mapping-{dimension}d')
        fields = run_case(case)
    return fields, captured[0]


def test_application_fields_and_scalars_match_native_solve(native_result):
    fields, raw = native_result
    result = to_compute_result(fields, evaluate(fields))
    dimension = fields.grid['dimension']
    assert result.converged == fields.run_status['converged']
    assert result.metadata['units']['Q'] == ('W/m' if dimension == 2 else 'W')
    for name in ('convergence_detail', 'envelope_valid', 'envelope_reasons',
                 'p_clip_hits', 'model_h_balance', 'true_h_balance'):
        assert_slots(result.diagnostics[name], raw[name])
    if dimension == 2:
        for name, source in (('Q_W', 'Q_total'), ('dP_A_Pa', 'dP_A'), ('dP_B_Pa', 'dP_B'),
                             ('T_out_A_K', 'T_out_A_K'), ('T_out_B_K', 'T_out_B_K')):
            assert getattr(result, name) == pytest.approx(raw[source])
        for name in ('Ta', 'Tb', 'Ts', 'P_fA', 'P_fB', 'ucA', 'vcA', 'ucB', 'vcB'):
            np.testing.assert_array_equal(result.fields[name], raw[name])
        for name in ('Q_A', 'Q_B', 'Q_net', 'energy_imbalance_rel',
                     'mass_imbalance_rel_A', 'mass_imbalance_rel_B'):
            assert result.residuals[name] == pytest.approx(raw[name], nan_ok=True)
        for axis in ('x', 'y'):
            np.testing.assert_array_equal(result.fields[f'd{axis}_arr'], fields.grid[f'd{axis}'])
        return
    assert isinstance(result, ComputeResult)

    # Native reduction must agree with the independently captured raw scalars.
    assert result.Q_W == pytest.approx(raw.get('Q_total', raw.get('Q')))
    assert result.dP_A_Pa == pytest.approx(raw.get('dP_A', raw.get('dP')))
    assert result.dP_B_Pa == pytest.approx(raw['dP_B'])
    assert result.T_out_A_K == pytest.approx(raw.get('T_out_A', raw.get('T_A_out')))
    assert result.T_out_B_K == pytest.approx(raw.get('T_out_B', raw.get('T_B_out')))

    # ── field arrays: same values surfaced under the ComputeResult keys ──
    field_map = {'Ta': 'Ta', 'Tb': 'Tb', 'Ts': 'Ts',
                 'P_fA': 'P_Pa', 'P_fB': 'P_Pa_B',
                 'ucA': 'uc_real', 'vcA': 'vc_real', 'wcA': 'wc_real',
                 'vmag_A': 'vmag', 'vmag_B': 'vmag_B'}
    for k_res, k_raw in field_map.items():
        assert k_res in result.fields, f"ComputeResult.fields missing {k_res!r}"
        a = result.fields[k_res]
        b = raw.get(k_raw)
        if b is None:
            assert a is None, f"{k_res}: result has value but raw {k_raw} is None"
        else:
            np.testing.assert_array_equal(np.asarray(a), np.asarray(b),
                                          err_msg=f"{k_res} != raw[{k_raw}]")

    # ── residuals dict surfaces the conservation diagnostics faithfully ──
    for key in ('Q_enthalpy_A', 'Q_enthalpy_B', 'Q_net',
                'energy_imbalance_rel', 'mass_imbalance_rel_A'):
        assert key in result.residuals, f"residuals missing {key!r}"
        rv = raw.get(key)
        if rv is not None and np.isfinite(float(rv)):
            assert result.residuals[key] == pytest.approx(float(rv)), key

    # ── B3 C4/C5: ComputeResult carries the full render/export contract
    # and is now the SINGLE carrier (raw_3d dict retired). New slots must
    # equal their raw counterparts.
    np.testing.assert_array_equal(
        np.asarray(result.fields['L_mm']), np.asarray(raw['L_mm']),
        err_msg="fields['L_mm'] != raw['L_mm']")
    assert result.props['u_A_in_mps'] == pytest.approx(raw['u_A'])
    assert result.props['T_in_A_K'] == pytest.approx(raw['T_in'])
    assert result.diagnostics['_max_outer'] == raw['_max_outer']
    assert result.diagnostics['mass_flow_A_kg_s'] == pytest.approx(
        raw['mass_flow_A_kg_s'])
    assert result.diagnostics['mass_flow_B_kg_s'] == pytest.approx(
        raw['mass_flow_B_kg_s'])
    assert result.diagnostics['mode'] == '3d'

    # ── B3 C5: the raw_3d carrier is GONE — the ComputeResult is what
    # window._result_3d now holds. Lock the FULL render/export contract:
    # every key ui/plot_3d_results.finalize_plots_3d +
    # _render_2d_slices_from_3d + main._export_results consume must be
    # present (fields arrays + dataclass scalars). If a future change
    # drops one, the 3D view / export silently blanks — this guard
    # catches it without a live PyVista panel.
    assert 'raw_3d' not in result.diagnostics, (
        "raw_3d carrier must be retired (B3 C5)")
    _fields_consumed = {
        'Ta', 'Tb', 'Ts', 'vmag_A', 'vmag_B',
        'P_fA', 'P_fB', 'L_mm',
        'dx', 'dy', 'dz', 'Lx', 'Ly', 'Lz', 'dir_A', 'dir_B',
        'ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB',
    }
    missing_f = _fields_consumed - set(result.fields)
    assert not missing_f, (
        f"ComputeResult.fields lost renderer keys: {sorted(missing_f)}")
    _diag_consumed = {'_ltne_info', '_max_outer', 'mode'}
    missing_d = _diag_consumed - set(result.diagnostics)
    assert not missing_d, (
        f"ComputeResult.diagnostics lost keys: {sorted(missing_d)}")
    # Scalars the renderer + export read off the dataclass / props.
    for attr in ('Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K'):
        assert hasattr(result, attr), f"ComputeResult missing {attr}"
    assert 'u_A_in_mps' in result.props and 'T_in_A_K' in result.props


@pytest.mark.parametrize('converged', [False, True])
def test_diagnostics_and_warnings_survive_mapping(native_result, converged):
    fields, _ = native_result
    metadata = mutable_data(fields.metadata)
    expected = dict(
        envelope_valid=False,
        envelope_reasons=['[A] supersonic: Ma_max = 1.20 >= 1'],
        p_clip_hits=17,
        convergence_detail={'simple_A': False, 'ltne': True},
        model_h_balance={'outer_index': 1, 'post_after_last_thermal': True,
                         'sides': {'A': {'physical_boundary_complete': False}}},
    )
    warnings = ['SIMPLE momentum solve did not converge to tol at: A',
                'Choked/supersonic flow: predicted outlet vacuum.']
    metadata['diagnostics'].update(expected, envelope_warnings=warnings)
    fields = replace(fields, metadata=metadata,
                     run_status={**fields.run_status, 'converged': converged})
    result = to_compute_result(fields, evaluate(fields))
    assert result.converged is converged
    for name, value in expected.items():
        assert result.diagnostics[name] == value
    assert set(warnings) <= set(result.warnings)


def test_unavailable_metrics_and_incomplete_execution_stay_visible(native_result):
    fields, _ = native_result
    incomplete = replace(fields, boundary_fluxes={})
    result = to_compute_result(incomplete, evaluate(incomplete))
    assert np.isnan(result.Q_W)
    assert result.metadata['metric_status']['Q'] == 'insufficient_data'
    assert any(w.startswith('Q: insufficient_data:') for w in result.warnings)
    for state in ('failed', 'cancelled'):
        incomplete = replace(fields, run_status={**fields.run_status, 'execution': state})
        with pytest.raises(ValueError, match='completed result'):
            to_compute_result(incomplete, evaluate(fields))
