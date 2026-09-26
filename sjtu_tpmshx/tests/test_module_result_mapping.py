"""Real public-result mapping retains the GUI/export and diagnostic contract."""
from dataclasses import replace
from types import SimpleNamespace
from sjtu_tpmshx.controllers.result_cache import ResultCache
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


def test_synthetic_3d_mapping_preserves_full_geometry_and_display_pressure():
    """Mapping only: distinguish original geometry and all pressure states."""
    from sjtu_tpmshx.domain.field_result import FieldResult
    from sjtu_tpmshx.domain.metric_spec import MetricSpec
    from sjtu_tpmshx.domain.performance_result import MetricValue, PerformanceResult

    cell = np.arange(24.).reshape(2, 3, 4)
    L_m, t_m = .004 + cell * .0001, .0003 + cell * .00001
    grid = dict(dimension=3, axis_order=('x', 'y', 'z'), length_unit='m',
                dx=np.array([.05, .15]), dy=np.array([.01, .03, .06]),
                dz=np.array([.005, .01, .015, .02]))
    native_fields = {name: cell + offset for offset, name in enumerate(
        ('Ta_display', 'Tb_display', 'Ts_display', 'ucA', 'vcA', 'wcA',
         'ucB', 'vcB', 'wcB', 'vmag_A', 'vmag_B', 'h_vA', 'h_vB'))}
    for side, pressure in (('A', 101325.), ('B', 202650.)):
        native_fields['P_f' + side + '_display'] = pressure + cell
        native_fields['P_gauge_' + side] = cell
        native_fields['P_report_' + side] = pressure + cell + 500.
    native = FieldResult('synthetic-result', 'synthetic-case', 'test', grid=grid,
        fields=native_fields, run_status=dict(execution='completed', converged=True),
        metadata=dict(parameters=dict(L=.2, H=.1, Lz=.05, extrap_reasons=[],
                          prepared=dict(geometry=dict(epsilon=.8, D_h=.003, A_0=.01))),
                      design_fields=dict(L_field_m=L_m, t_field_m=t_m),
                      diagnostics=dict(dir_A=1, dir_B=4),
                      application=dict(coeffs={}, props={}),
                      model_metadata={}, df_metadata={}, quantity_basis='total', notices=[]))
    performance = PerformanceResult('synthetic-metrics', native.result_id, {
        name: MetricValue(value, MetricSpec(name, unit,
            'pressure_face_v1' if name.startswith('dP') else 'native_boundary_v1'))
        for name, value, unit in (('Q', 100., 'W'), ('Q_A', 100., 'W'), ('Q_B', -100., 'W'),
                                 ('dP_A', 10., 'Pa'), ('dP_B', 20., 'Pa'),
                                 ('T_out_A', 330., 'K'), ('T_out_B', 310., 'K'))})

    result = to_compute_result(native, performance)
    np.testing.assert_array_equal(result.fields['L_mm'], L_m * 1e3)
    np.testing.assert_array_equal(result.fields['t_mm'], t_m * 1e3)
    for name in ('ucA', 'vcA', 'wcA', 'ucB', 'vcB', 'wcB', 'vmag_A', 'vmag_B'):
        np.testing.assert_array_equal(result.fields[name], native_fields[name])
    for side in ('A', 'B'):
        np.testing.assert_array_equal(result.fields['P_f' + side],
                                      native_fields['P_f' + side + '_display'])
    for name in ('dx', 'dy', 'dz'):
        np.testing.assert_array_equal(result.fields[name], grid[name])


# Fixed from the real scenarios below on pre-producer-refactor main 736c0a8.
# Keep these expectations independent of the current raw/diagnostic mappings.
_DIAGNOSTICS_2D = frozenset('''
    P_in_realized_A P_in_realized_B P_in_shoot_resid_A P_in_shoot_resid_B
    Q_A Q_B Q_enthalpy_A Q_enthalpy_B Q_net Q_richardson_warn
    Q_solid_richardson Q_total T_out_A_K T_out_B_K convergence_detail dP_A dP_B
    df_metadata energy_imbalance_rel envelope_reasons envelope_valid
    mass_flow_A_kg_s_per_m mass_flow_B_kg_s_per_m mass_imbalance_rel_A
    mass_imbalance_rel_B model_h_balance p_clip_hits residuals_A residuals_B
    richardson_info sco2_nu_observations solver_converged true_h_balance
    ucA_disp ucB_disp vcA_disp vcB_disp warnings_list
'''.split())
_DIAGNOSTICS_3D = frozenset('''
    AB_interior Lx Ly Lz P_in_realized_A P_in_realized_B
    P_in_shoot_resid_A P_in_shoot_resid_B Q Q_AB_imbalance_rel Q_enthalpy_A
    Q_enthalpy_B Q_interior Q_net Q_sA Q_sA_interior Q_sB Q_sB_interior
    Q_solid_B Q_total T_A_out T_B_out T_in T_out_A T_out_B _ltne_info
    _ltne_max_iter _max_outer _needs_full_validate convergence_detail dP dP_A
    dP_B df_metadata dir_A dir_B energy_imbalance_rel envelope_reasons
    envelope_valid envelope_warnings eps_A_strict eps_A_strict_cellmax
    eps_B_strict eps_B_strict_cellmax mass_flow_A_kg_s mass_flow_B_kg_s
    mass_imbalance_rel_A mass_imbalance_rel_B model_h_balance p_clip_hits
    sco2_nu_observations solver_converged true_h_balance u_A
'''.split())
_AUDIT_DIAGNOSTICS_3D = frozenset('''
    _audit_P_inA _audit_P_inB _audit_T_inA _audit_T_inB _audit_cp_A _audit_cp_B
    _audit_eps _audit_fA _audit_fB _audit_m_dot_A_simple _audit_m_dot_B_phys_in
    _audit_m_dot_B_phys_out _audit_m_dot_B_simple _audit_sA_face _audit_sB_face
    _audit_u_A _audit_u_B
'''.split())
_CONVERGENCE_2D = frozenset('''
    enthalpy_balance_ok envelope_ok inlet_pressure
    ltne_iterations ltne_ok ltne_residual model_h_balance_ok outer_converged
    outer_hit_cap outer_iters richardson_ok simple_ok
'''.split())
# The unreachable NaN replacement and its energy_nan_hit diagnostic are retired;
# nonfinite thermal returns raise before producing a result.
_CONVERGENCE_3D = frozenset('''
    envelope_ok fields_finite inlet_pressure ltne_ok outer_anderson
    outer_converged outer_dT outer_hit_cap outer_iters simple_A simple_B
    simple_exit_A simple_exit_B simple_nonconv simple_nonconv_final
    simple_nonconv_transient simple_ok
'''.split())
_INLET_PRESSURE_KEYS = frozenset('''
    definition iterations minimum_Pa outlet_Pa outlet_gauge_Pa passed realized_Pa
    relative_error relative_tolerance specified_Pa
'''.split())


def _assert_producer_diagnostics(raw, diagnostics, expected_keys):
    assert diagnostics.keys() == expected_keys, (
        f'diagnostic keys: missing={sorted(expected_keys - diagnostics.keys())}, '
        f'unexpected={sorted(diagnostics.keys() - expected_keys)}')
    # The former capture rule separately checks classification and shared values;
    # it cannot detect a key missing from both new mappings on its own.
    expected = {key: value for key, value in raw.items()
                if not isinstance(value, np.ndarray)
                and key not in ('_native_evidence', 'application')}
    assert diagnostics.keys() == expected.keys()
    for key, value in expected.items():
        assert diagnostics[key] is value, key


def _assert_3d_diagnostics(raw, diagnostics, *, frozen_B=False, audit=False):
    expected = _DIAGNOSTICS_3D
    none_keys = {'true_h_balance'}
    if frozen_B:
        expected |= {'P_Pa_B', 'vmag_B'}
        none_keys |= {'P_Pa_B', 'vmag_B', 'T_B_out', 'T_out_B', 'dir_B',
                      'eps_B_strict', 'eps_B_strict_cellmax', 'mass_flow_B_kg_s',
                      'model_h_balance'}
    if audit:
        expected |= _AUDIT_DIAGNOSTICS_3D
        if frozen_B:
            expected |= {'_audit_in_mask_B',
                         '_audit_ltne_mask_B', '_audit_out_mask_B'}
            none_keys |= {'_audit_in_mask_B', '_audit_ltne_mask_B',
                          '_audit_out_mask_B', '_audit_T_inB', '_audit_cp_B',
                          '_audit_fB', '_audit_m_dot_B_phys_in', '_audit_m_dot_B_phys_out',
                          '_audit_m_dot_B_simple', '_audit_sB_face', '_audit_u_B'}
        for side in ('A',) if frozen_B else ('A', 'B'):
            assert diagnostics[f'_audit_s{side}_face'].keys() == {
                'dir_real', 'dx', 'dy', 'dz', 'eps', 'inlet_frac', 'outlet_coeff',
                'outlet_frac', 'rho', 'solver_to_real_perm', 'u', 'v', 'w'}
            assert diagnostics[f'_audit_f{side}'].keys() == {
                'dir', 'in_ctr', 'in_w', 'out_ctr', 'out_w'}
    _assert_producer_diagnostics(raw, diagnostics, expected)
    for key in none_keys:
        assert diagnostics[key] is None, key
    detail = diagnostics['convergence_detail']
    assert detail.keys() == _CONVERGENCE_3D
    assert detail['inlet_pressure'].keys() == {'A', 'B'}
    assert diagnostics['df_metadata'].keys() == {'mode', 'A', 'B'}
    if frozen_B:
        assert detail['simple_B'] is detail['simple_exit_B'] is None
        assert detail['inlet_pressure']['B'] is diagnostics['df_metadata']['B'] is None
    else:
        balance = diagnostics['model_h_balance']
        assert {'outer_index', 'post_after_last_thermal', 'thermal_state',
                'physical_boundary_complete', 'sides'} <= balance.keys()
        assert balance['sides'].keys() == {'A', 'B'}
        for side in ('A', 'B'):
            assert {'physical_boundary_complete', 'physical_external_inward_W',
                    'faces'} <= balance['sides'][side].keys()
    for side in ('A',) if frozen_B else ('A', 'B'):
        assert detail['inlet_pressure'][side].keys() == _INLET_PRESSURE_KEYS
        assert detail[f'simple_{side}'].keys() == {
            'convergence_mode', 'exit_reason', 'final_res', 'final_res_mass_global',
            'final_res_mass_local', 'final_res_mom', 'iterations',
            'outlet_backflow_frac', 'res_norm_ref'}


@pytest.mark.parametrize('keys, missing', [
    pytest.param(_DIAGNOSTICS_2D, 'Q_total', id='2d'),
    pytest.param(_DIAGNOSTICS_3D, 'Q_total', id='3d'),
    pytest.param(_DIAGNOSTICS_3D | {'P_Pa_B', 'vmag_B'},
                 'P_Pa_B', id='3d-none-placeholder'),
])
def test_diagnostic_contract_rejects_joint_field_loss(keys, missing):
    raw = dict.fromkeys(keys)
    diagnostics = raw.copy()
    _assert_producer_diagnostics(raw, diagnostics, keys)
    del raw[missing]
    del diagnostics[missing]
    with pytest.raises(AssertionError, match=missing):
        _assert_producer_diagnostics(raw, diagnostics, keys)


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


@pytest.fixture(scope='module', params=[2, 3, '2-partial'])
def native_result(request):
    dimension = 3 if request.param == 3 else 2
    config = baseline_config() if dimension == 2 else _small_air_air_cfg()
    if request.param == '2-partial':
        config = replace(config,
            geometry=replace(config.geometry, L_dom_m=.06, H_dom_m=.03, t_wall_mm=.6),
            solver=SolverConfig(Nx=8, Ny=10, Nz=1, max_outer_ltne=2, max_iter_simple=500),
            bc_A=PartialBCConfig(dir=0, in_ctr=.015, in_w=.014, out_ctr=.015, out_w=.014))
    module = importlib.import_module(
        'sjtu_tpmshx.solvers.backends.python.'
        + ('two_d' if dimension == 2 else 'three_d') + '.result_capture')
    captured = []
    capture = module.capture_result
    def record(*args):
        raw = args[1] if dimension == 2 else args[3]
        diagnostics = args[-1]
        if dimension == 2:
            expected = (_DIAGNOSTICS_2D - {'ucA_disp', 'vcA_disp'}
                        if request.param == '2-partial' else _DIAGNOSTICS_2D)
            _assert_producer_diagnostics(raw, diagnostics, expected)
            for key in expected & {'ucA_disp', 'vcA_disp', 'ucB_disp', 'vcB_disp'}:
                assert diagnostics[key] is None, key
            assert diagnostics['true_h_balance'] is None
            detail = diagnostics['convergence_detail']
            assert detail.keys() == _CONVERGENCE_2D
            assert detail['inlet_pressure'].keys() == {'A', 'B'}
            for side in ('A', 'B'):
                assert detail['inlet_pressure'][side].keys() == _INLET_PRESSURE_KEYS
            assert diagnostics['df_metadata'].keys() == {'mode', 'A', 'B'}
            assert diagnostics['richardson_info'].keys() == {
                'converged', 'extrapolated', 'iterations', 'model_h_balance', 'residual'}
            assert diagnostics['model_h_balance'].keys() == {'main', 'fine'}
            for grid in ('main', 'fine'):
                balance = diagnostics['model_h_balance'][grid]
                assert {'A', 'B', 'outer_index', 'post_after_last_thermal',
                        'physical_boundary_complete', 'passed', 'state'} <= balance.keys()
                for side in ('A', 'B'):
                    assert {'physical_boundary_complete', 'Q_advective_W_per_m',
                            'h_faces_W_per_m', 'mass_faces_kg_s_per_m'} <= balance[side].keys()
        else:
            _assert_3d_diagnostics(raw, diagnostics)
        captured.append(raw)
        result = capture(*args)
        assert result.metadata['diagnostics'].keys() == diagnostics.keys()
        assert_slots(result.metadata['diagnostics'], diagnostics)
        return result
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, 'capture_result', record)
        case = prepare_case(config, case_id=f'mapping-{dimension}d')
        fields = run_case(case)
    if request.param == '2-partial':
        assert 'ucA_display' in fields.fields
        assert not np.array_equal(fields.fields['ucA'], fields.fields['ucA_display'])
    return fields, captured[0]


@pytest.mark.parametrize('frozen_B', [False, True])
@pytest.mark.parametrize('audit', [False, True])
def test_legacy_3d_producer_preserves_optional_diagnostics(monkeypatch, frozen_B, audit):
    from sjtu_tpmshx.pipelines import run_stack_3d as stack
    from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d

    cfg = _cheap_3d(max_outer_ltne=1, _emit_audit=audit)
    # Exercise ordinary reporting; compact sweep CSV expects a solved B outlet.
    cfg['sweep_profile'] = None
    if frozen_B:
        cfg['fluid_B_cfg'] = None
    assemble = stack._assemble_3d_verdict
    observed = []

    def record(prob, outer, metrics):
        raw, diagnostics = assemble(prob, outer, metrics)
        _assert_3d_diagnostics(raw, diagnostics, frozen_B=frozen_B, audit=audit)
        observed.append(raw)
        if frozen_B:
            assert raw['P_Pa_B'] is raw['vmag_B'] is None
            assert diagnostics['P_Pa_B'] is diagnostics['vmag_B'] is None
        if audit:
            assert '_audit_sA_face' in diagnostics
            assert '_audit_K_ffA' not in diagnostics
            assert not np.shares_memory(raw['_audit_K_ffA'], prob.K_ffA)
            assert not np.shares_memory(diagnostics['_audit_sA_face']['u'], prob.sA.u)
            if frozen_B:
                assert diagnostics['_audit_sB_face'] is None
                assert diagnostics['_audit_in_mask_B'] is None
        else:
            assert not any(key.startswith('_audit_') for key in raw)
        return raw, diagnostics

    monkeypatch.setattr(stack, '_assemble_3d_verdict', record)
    result = stack._run_3d_stack(cfg)
    assert len(observed) == 1 and result is observed[0]


def test_application_fields_and_scalars_match_native_solve(native_result):
    fields, raw = native_result
    performance = evaluate(fields)
    result = to_compute_result(fields, performance)
    dimension = fields.grid['dimension']
    assert result.converged == fields.run_status['converged']
    assert result.metadata['units']['Q'] == ('W/m' if dimension == 2 else 'W')
    assert result.Q_W == performance.metrics['Q'].value
    for name in ('Q_A', 'Q_B', 'energy_imbalance_rel'):
        assert result.residuals[name] == performance.metrics[name].value
    assert result.residuals['Q_net'] == result.residuals['Q_A'] + result.residuals['Q_B']
    for name in ('convergence_detail', 'envelope_valid', 'envelope_reasons',
                 'p_clip_hits', 'model_h_balance', 'true_h_balance'):
        assert_slots(result.diagnostics[name], raw[name])
    if dimension == 2:
        for side in ('A', 'B'):
            metric = performance.metrics[f'dP_{side}']
            assert metric.spec.definition_version == 'pressure_face_v1'
            assert getattr(result, f'dP_{side}_Pa') == metric.value
        for name, source in (('T_out_A_K', 'T_out_A_K'), ('T_out_B_K', 'T_out_B_K')):
            assert getattr(result, name) == pytest.approx(raw[source])
        for name in ('Ta', 'Tb', 'Ts', 'P_fA', 'P_fB', 'ucA', 'vcA', 'ucB', 'vcB'):
            np.testing.assert_array_equal(result.fields[name], raw[name])
        for name in ('mass_imbalance_rel_A', 'mass_imbalance_rel_B'):
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
    for key in ('Q_enthalpy_A', 'Q_enthalpy_B', 'mass_imbalance_rel_A'):
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
    np.testing.assert_array_equal(result.fields['t_mm'],
                                  fields.metadata['design_fields']['t_field_m'] * 1e3)
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
        'P_fA', 'P_fB', 'L_mm', 't_mm',
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


def test_native_result_reaches_gui_diagnostics_and_display_cache(native_result):
    from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin
    fields, _ = native_result
    result = to_compute_result(fields, evaluate(fields))
    window = SimpleNamespace(cache=ResultCache())
    RunResultsMixin.write_result(window, result)
    if fields.grid['dimension'] == 3:
        for side in ('A', 'B'):
            assert window._diag_summary['Q_' + side] == pytest.approx(
                result.residuals['Q_' + side], nan_ok=True)
        assert window._diag_summary['closure_basis'] == '主网格两侧有符号焓流'
        text = RunResultsMixin._diag_summary_text(window)
        assert '两侧焓流: Q_A' in text and '能量闭合（主网格两侧有符号焓流）' in text
    else:
        for name in ('ucA', 'vcA', 'ucB', 'vcB'):
            np.testing.assert_array_equal(window.cache.get_result('2d').fields[name], fields.fields[name])
            np.testing.assert_array_equal(window.cache.get_result('2d').fields[name + '_disp'],
                                          fields.fields.get(name + '_display'))


def test_diagnostic_text_includes_recorded_stage_seconds():
    from sjtu_tpmshx.ui.mixins.run_results import RunResultsMixin
    window = SimpleNamespace(_diag_summary={'timings_s': {
        'prepare': 0.125, 'solve': 12.5, 'postprocess': 0.25, 'display': 0.375}})
    text = RunResultsMixin._diag_summary_text(window)
    assert '阶段耗时：准备 0.125 s · 求解 12.500 s · 后处理 0.250 s · 显示 0.375 s' in text


def test_mapping_keeps_recorded_state_after_producer_drafts_change(native_result):
    fields, raw = native_result
    expected = to_compute_result(fields, evaluate(fields))
    # Change the original backend carrier after capture, including display,
    # headline, direction, and failure data. The immutable archive owns its run.
    changed = {**raw, 'Ta': raw['Ta'] + 100., 'Tb': raw['Tb'] - 100.,
               'T_out_A_K': -999., 'T_out_A': -999., 'Q_total': -999., 'Q': -999.,
               'dir_A': 1, 'dir_B': 3, 'solver_converged': False}
    original = dict(raw)
    try:
        raw.update(changed)
        actual = to_compute_result(fields, evaluate(fields))
        for name in ('Q_W', 'T_out_A_K', 'T_out_B_K', 'converged', 'residuals'):
            assert_slots(getattr(actual, name), getattr(expected, name))
    finally:
        raw.clear()
        raw.update(original)
