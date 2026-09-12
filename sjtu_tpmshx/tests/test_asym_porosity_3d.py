"""Asymmetric porosity (ε_A ≠ ε_B, offset-isosurface δ) — Phase 1 wiring tests.

Guards the δ=0 bit-identity contract (zero regression) and the δ>0 asymmetric
path end-to-end, plus the κ correction layer. Mirrors the risk list in the
implementation plan (kernel dual-ε consistency, balance-coef match, κ=1 ULP).
"""
import numpy as np
import pytest

from sjtu_tpmshx.models.asym_split import _asym_split_A, _eps_sides_for_run
from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
from sjtu_tpmshx.runs._out._golden_3d import _air_air_cfg
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
    """delta_levelset=0.0 in cfg == no key at all → identical headline scalars."""
    r0 = _run_3d_stack(_air_air_cfg())
    rd = _run_3d_stack(_air_air_cfg(delta_levelset=0.0))
    for k in ('Q', 'dP', 'dP_B', 'T_A_out', 'T_B_out'):
        assert r0[k] == rd[k], f"{k}: {r0[k]} != {rd[k]}"


@pytest.mark.parametrize("conservative", [False, True])
def test_asym_delta_runs_and_changes_result(conservative):
    """δ>0 runs end-to-end (NotImplementedError gone) on cc + stag kernels,
    produces finite output, and actually differs from symmetric."""
    base = _run_3d_stack(_air_air_cfg(conservative_ltne=conservative))
    asym = _run_3d_stack(_air_air_cfg(delta_levelset=0.6,
                                      conservative_ltne=conservative))
    assert np.isfinite(asym['Q']) and asym['Q'] > 0.0
    assert np.isfinite(asym['dP']) and np.isfinite(asym['dP_B'])
    # asymmetry must move at least one headline scalar
    assert (asym['Q'] != base['Q']) or (asym['dP_B'] != base['dP_B'])


def test_asym_conservation_certificate_machine_zero():
    """Risk #1/#2: dual-ε kernel + per-side balance coef stay STRICTLY
    conservative at δ>0. The incompressible water-B strict-conservation
    certificate must remain machine-zero (≪1) — an inconsistent per-side ε
    switch (kernel vs balance-coef) would blow it up to O(0.01–1)."""
    cfg = _air_air_cfg(delta_levelset=0.6, conservative_ltne=True,
                       u_B=0.5, fluid_type_B='water',
                       fluid_B_cfg=dict(dir=3, in_ctr=0.021, in_w=0.042,
                                        out_ctr=0.021, out_w=0.042,
                                        in_z_ctr=0.021, in_z_w=0.042,
                                        out_z_ctr=0.021, out_z_w=0.042))
    r = _run_3d_stack(cfg)
    assert np.isfinite(r['Q']) and r['Q'] > 0.0
    assert r['eps_A_strict'] < 1e-9, f"A-side conservation broke: {r['eps_A_strict']}"
    assert r['eps_B_strict'] < 1e-9, f"B-side conservation broke: {r['eps_B_strict']}"
