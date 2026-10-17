"""Asymmetric porosity (ε_A ≠ ε_B, offset-isosurface δ) — Phase 1 wiring tests.

Guards the δ=0 bit-identity contract (zero regression) and the δ>0 asymmetric
path end-to-end, plus the κ correction layer. Mirrors the risk list in the
implementation plan (kernel dual-ε consistency, balance-coef match, κ=1 ULP).
"""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.models.asym_split import _asym_split_A, _eps_sides_for_run
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.cases_3d import air_air_config
from sjtu_tpmshx.df_surrogate import kappa_asym


# ── split + per-side void fraction ───────────────────────────────────────────

def test_split_delta0_is_exactly_half():
    assert _asym_split_A({'delta_levelset': 0.0}, 'Gyroid', 7.0, 0.6) == 0.5


@pytest.mark.parametrize("tpms", ["Gyroid", "Diamond"])
def test_split_positive_delta_grows_A(tpms):
    s = _asym_split_A({'delta_levelset': 0.6}, tpms, 7.0, 0.6)
    assert 0.5 < s < 1.0


def test_eps_sides_delta0_object_identity():
    """δ=0 MUST return the same eps_f_arr object → golden bit-identity."""
    eps = np.full((3, 3, 3), 0.74)
    epsf = eps / 2.0
    a, b = _eps_sides_for_run({'delta_levelset': 0.0}, 'Gyroid', 7.0, 0.6, eps, epsf)
    assert a is epsf and b is epsf


def test_eps_sides_delta_pos_total_preserved():
    eps = np.full((3, 3, 3), 0.74)
    epsf = eps / 2.0
    a, b = _eps_sides_for_run({'delta_levelset': 0.6}, 'Gyroid', 7.0, 0.6, eps, epsf)
    assert np.allclose(a + b, eps)          # total ε preserved (cfg['eps'] honoured)
    assert a.mean() > b.mean()              # A is the gained (big-channel) side


# ── κ correction layer ───────────────────────────────────────────────────────

def test_kappa_identity_guards():
    kappa_asym.clear()
    assert kappa_asym.kappa_KcF('Gyroid', 0.57, 0.37) == (1.0, 1.0)              # env off
    assert kappa_asym.kappa_KcF('Gyroid', 0.37, 0.37, enabled=True) == (1.0, 1.0)  # r=1
    assert kappa_asym.kappa_KcF('Gyroid', 0.57, 0.37, enabled=True) == (1.0, 1.0)  # no table


def test_kappa_table_applies_and_clears():
    kappa_asym.clear()
    kappa_asym.set_kappa_table('Gyroid', lambda r: 1.0 + 0.5 * (r - 1.0),
                               lambda r: 1.0 - 0.2 * (r - 1.0))
    kK, kcF = kappa_asym.kappa_KcF('Gyroid', 0.555, 0.37, enabled=True)   # r=1.5
    assert kK == pytest.approx(1.25) and kcF == pytest.approx(0.9)
    kappa_asym.clear()
    assert not kappa_asym.has_table('Gyroid')


# ── end-to-end 3D stack ──────────────────────────────────────────────────────

def test_delta0_explicit_matches_baseline_bit_identical():
    config = air_air_config()
    baseline = run_case(prepare_case(config, case_id='asym-default')).metadata['diagnostics']
    config.geometry.delta_levelset = 0.
    explicit = run_case(prepare_case(config, case_id='asym-zero')).metadata['diagnostics']
    for key in ('Q', 'dP', 'dP_B', 'T_A_out', 'T_B_out'):
        assert baseline[key] == explicit[key]


@pytest.mark.parametrize('conservative', [False, True])
def test_asym_delta_runs_and_changes_result(conservative):
    from sjtu_tpmshx.domain.module_ports import RunControl
    from sjtu_tpmshx.domain.module_ports import resolve_control
    from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    control = resolve_control(RunControl())
    driver = NativeFull3DDriver(control.native_library, table_directory=control.native_table_directory)
    results = []
    for delta in (0., .6):
        config = air_air_config()
        config.geometry.delta_levelset = delta
        case = prepare_case(config, case_id='asymmetric-native')
        cfg, prepared = build_execution_inputs(case)
        cfg['conservative_ltne'] = conservative
        results.append(driver.run_prepared(cfg, prepared, control))
    base, asym = results
    assert np.isfinite(asym['duty'][0]) and asym['duty'][0] > 0.
    assert np.all(np.isfinite(asym['pressure_drop']))
    assert asym['duty'][0] != base['duty'][0] or asym['pressure_drop'][1] != base['pressure_drop'][1]


def test_asym_conservation_certificate_machine_zero():
    config = air_air_config()
    # Resolve the thermal state below this test's strict energy limit.
    config.solver.model_h_temperature_tol_K = 1e-9
    config.solver.model_h_q_relative_tol = 1e-10
    config.geometry.delta_levelset = .6
    config.fluid_B = replace(config.fluid_B, type='water', u_mps=.5)
    config.bc_B = replace(config.bc_B, in_ctr=.021, out_ctr=.021)
    result = run_case(prepare_case(config, case_id='asymmetric-conservation'))
    r = result.metadata['diagnostics']
    assert np.isfinite(r['Q']) and r['Q'] > 0.
    assert r['eps_A_strict'] < 1e-9
    assert r['eps_B_strict'] < 1e-9
