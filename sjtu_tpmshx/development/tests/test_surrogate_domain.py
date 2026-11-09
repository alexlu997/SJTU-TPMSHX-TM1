"""Sanity tests for df_surrogate.surrogate_domain.check_surrogate_domain_at_point.

Covers:
  * In-window inputs return empty list
  * Out-of-grid L/t raise by default and become warnings when extrapolation is allowed
  * Out-of-window Re (via velocity) same behavior
  * Env var TPMSHX_ALLOW_EXTRAP=1 forces allow_extrap=True
  * side='A' / 'B' label propagates to reason text
"""
from __future__ import annotations

import pytest

from sjtu_tpmshx.shared.df_surrogate.surrogate_domain import (
    check_surrogate_domain_at_point,
    _SURROGATE_L_MM, _SURROGATE_T_MM,
)


# ─── In-window — clean pass ────────────────────────────────────────


def test_in_window_returns_empty():
    """Reasonable Shanghai inputs (mid-window) → no reasons."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
        u=5.0, T=350.0, P=101325.0, side='A',
        allow_extrap=False)
    assert reasons == []


# ─── Out-of-window — raise vs warn ─────────────────────────────────


def test_oow_L_below_min_raises_default():
    """L = 3 mm < 4 mm window → ValueError when allow_extrap=False."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=3.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_L_above_max_raises_default():
    """L = 10 mm > 8 mm window."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_t_above_max_raises_default():
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.61, k_s=16.0,
            u=5.0, T=350.0, side='A')


def test_oow_L_with_allow_extrap_returns_reasons():
    """allow_extrap=True converts raise → warn + return reason list."""
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A', allow_extrap=True)
    assert len(reasons) >= 1
    assert any('L_cell' in r for r in reasons)


def test_oow_t_with_allow_extrap_returns_reasons():
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.61, k_s=16.0,
            u=5.0, T=350.0, side='B', allow_extrap=True)
    assert len(reasons) >= 1
    assert any('thickness' in r for r in reasons)


def test_oow_velocity_too_low_raises():
    """Very low u → Re below window minimum 400."""
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
            u=0.1, T=350.0, side='A')


# ─── side label propagation ────────────────────────────────────────


def test_side_label_in_reason():
    """side='B' should appear in any Re-related failure message."""
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=6.0, t_mm=0.4, k_s=16.0,
            u=0.1, T=350.0, side='B', allow_extrap=True)
    re_reasons = [r for r in reasons if 'Re' in r]
    assert any('B' in r for r in re_reasons), \
        f"side='B' label missing in: {re_reasons}"


# ─── Env var override ──────────────────────────────────────────────


def test_env_var_forces_allow_extrap(monkeypatch):
    """TPMSHX_ALLOW_EXTRAP=1 should let oow inputs pass with warning."""
    monkeypatch.setenv('TPMSHX_ALLOW_EXTRAP', '1')
    with pytest.warns(UserWarning):
        reasons = check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A', allow_extrap=False)
    assert len(reasons) >= 1


def test_env_var_off_still_raises(monkeypatch):
    """No env var + default allow_extrap=False → raise as usual."""
    monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    with pytest.raises(ValueError):
        check_surrogate_domain_at_point(
            'Diamond', L_mm=10.0, t_mm=0.4, k_s=16.0,
            u=5.0, T=350.0, side='A')


# ─── Boundary cases ────────────────────────────────────────────────


def test_exactly_at_L_lower_bound():
    """L = 4.0 (lower bound exactly) — should not produce an L-related reason.
    Use u high enough to also keep Re inside [400, 16000]."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=_SURROGATE_L_MM[0], t_mm=0.4, k_s=16.0,
        u=10.0, T=350.0, side='A', allow_extrap=True)
    L_reasons = [r for r in reasons if 'L_cell' in r]
    assert L_reasons == []


def test_exactly_at_t_upper_bound():
    """t = 0.6 is a supported CFD node."""
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=6.0, t_mm=_SURROGATE_T_MM[-1], k_s=16.0,
        u=5.0, T=350.0, side='A', allow_extrap=False)
    t_reasons = [r for r in reasons if 'thickness' in r or 't =' in r]
    assert t_reasons == []


def test_between_geometry_nodes_is_supported():
    reasons = check_surrogate_domain_at_point(
        'Diamond', L_mm=5.5, t_mm=0.45, k_s=16.0,
        u=5.0, T=350.0, side='A', allow_extrap=False)
    assert reasons == []


@pytest.mark.parametrize('L_mm,u,has_nu,has_geometry', [
    (7, 0.1, True, False), (9, 5, False, True), (9, 0.1, True, True),
])
@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('policy', ['allow', 'reject', 'env'])
def test_separate_nu_reasons_preserves_all_guards(monkeypatch, L_mm, u,
                                                has_nu, has_geometry, side, policy):
    if policy == 'env':
        monkeypatch.setenv('TPMSHX_ALLOW_EXTRAP', '1')
    else:
        monkeypatch.delenv('TPMSHX_ALLOW_EXTRAP', raising=False)
    args = ('Gyroid', L_mm, 0.4, 16, u, 350)
    nu_reasons = []
    if policy == 'reject':
        with pytest.raises(ValueError):
            check_surrogate_domain_at_point(*args, side=side, nu_reasons=nu_reasons)
        assert not nu_reasons
        return
    with pytest.warns(UserWarning):
        geometry = check_surrogate_domain_at_point(
            *args, side=side, allow_extrap=policy == 'allow', nu_reasons=nu_reasons)
    with pytest.warns(UserWarning):
        standalone = check_surrogate_domain_at_point(
            *args, side=side, allow_extrap=policy == 'allow')
    assert bool(nu_reasons) is has_nu
    assert bool(geometry) is has_geometry
    assert nu_reasons + geometry == standalone
    assert all(f'Fluid {side}:' in reason for reason in nu_reasons)
    assert all('CFD grid' in reason for reason in geometry)
