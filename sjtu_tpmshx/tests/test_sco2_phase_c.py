"""Phase C (near-critical sCO2) enablement (2026-06-27).

Covers the property-backend additions that Phase C needs over Phase A:
  * sco2_temperature(h, P) — the enthalpy->T inverse used to carry the energy
    balance in enthalpy across the pseudocritical cp spike;
  * vectorised sco2_prop queries for per-cell property
    refresh through the spike.

The historical project field-solver cross-check is indexed in
docs/history/retired-tools.md; it was not an experimental gate.
These property-backend tests remain part of the current solver contract.
"""
import numpy as np
import pytest

from sjtu_tpmshx.models import sco2_props as S


# ── enthalpy inverse ────────────────────────────────────────────────
def test_sco2_temperature_round_trips_enthalpy():
    """T -> h -> T recovers the temperature (Span-Wagner monotone in h at P)."""
    P = 8.0e6
    for T in (320.0, 340.0, 371.0, 450.0):
        h = S.sco2_prop('H', T, P)
        assert S.sco2_temperature(h, P) == pytest.approx(T, abs=1e-3)


def test_sco2_temperature_through_pseudocritical():
    """Across the 7.7 MPa pseudocritical spike the inverse stays single-valued
    and monotone (no branch flip where cp peaks)."""
    P = 8.0e6
    Ts = np.linspace(307.5, 371.0, 25)
    hs = np.array([S.sco2_prop('H', T, P) for T in Ts])
    assert np.all(np.diff(hs) > 0)                      # h strictly increasing
    back = np.array([S.sco2_temperature(h, P) for h in hs])
    assert np.allclose(back, Ts, atol=1e-2)


# ── vectorised field helpers ────────────────────────────────────────
def test_sco2_field_helpers_match_scalar():
    P = 8.0e6
    T = np.array([[320.0, 340.0], [360.0, 371.0]])
    rho = S.sco2_prop('D', T, P)
    cp = S.sco2_prop('C', T, P)
    assert rho.shape == T.shape and cp.shape == T.shape
    # match the cached scalar primitives cell-by-cell
    assert rho[0, 0] == pytest.approx(S.sco2_prop('D', 320.0, P), rel=1e-9)
    assert cp[1, 1] == pytest.approx(S.sco2_prop('C', 371.0, P), rel=1e-9)




def test_sco2_rho_cp_spikes_near_pseudocritical():
    """The whole point of Phase C: rho*cp swings strongly toward Tpc(7.7)~306 K."""
    P = 8.0e6
    rc_far = np.prod(S.sco2_prop(('D', 'C'), 371., P))
    rc_near = np.prod(S.sco2_prop(('D', 'C'), 308., P))
    assert rc_near > 5.0 * rc_far                       # order-of-magnitude swing


# ── registry primitives accept SCALARS and FIELDS ──────────────────────
# Regression for the 2026-06-27 2D-GUI integration bug: the variable-property
# outer loop calls the registry rho/cp/mu/k with a whole T FIELD and a local-P
# FIELD; the cached scalar primitive raised `unhashable type: numpy.ndarray`.
# No pytest exercised the array path, so the break was silent until a smoke run.
def test_sco2_prop_scalar_and_field_dispatch():
    from sjtu_tpmshx.models.fluid_props import FLUIDS
    m = FLUIDS['sco2']
    P = 8.0e6
    # scalar path (cached) returns a float
    rho_s = m.rho(371.0, P)
    assert isinstance(rho_s, float) and rho_s > 0

    # field path: T array, scalar P — shape preserved, matches scalar cell-by-cell
    T = np.array([[320.0, 340.0], [360.0, 371.0]])
    rho_f = m.rho(T, P)
    assert rho_f.shape == T.shape
    assert rho_f[1, 1] == pytest.approx(m.rho(371.0, P), rel=1e-9)
    for fn in (m.cp, m.mu, m.k):
        assert fn(T, P).shape == T.shape

    # field path: T array AND P array (per-cell local pressure), broadcast
    Pf = np.full_like(T, P)
    assert np.allclose(m.rho(T, Pf), rho_f, rtol=1e-12)


def test_sco2_prop_missing_pressure_raises():
    from sjtu_tpmshx.models.fluid_props import FLUIDS
    with pytest.raises(ValueError, match="require pressure"):
        FLUIDS['sco2'].rho(371.0)              # P omitted → clear error


@pytest.mark.parametrize('temperature,pressure', [
    (310., 8e6), (np.full((1, 1, 1), 310.), 8e6),
    (np.array([280., 300., 304.13, 307., 310., 320., 400., 700.])[:, None],
     np.array([7.9e6, 8e6, 12e6, 16e6])[None, :]),
])
def test_joint_properties_match_separate_heos_queries(monkeypatch, temperature, pressure):
    keys = ('D', 'V', 'L', 'C')
    expected = np.array([S.sco2_prop(key, temperature, pressure) for key in keys])
    original, calls = S._PropsSI, []

    def query(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(S, '_PropsSI', query)
    actual = S.sco2_prop(keys, temperature, pressure)
    np.testing.assert_array_equal(actual, expected)
    assert actual.flags.c_contiguous
    assert calls == [keys]
    with pytest.raises(ValueError, match='temperature'):
        S.sco2_prop(keys, np.array([310., 701.]), pressure)
    assert calls == [keys]  # Invalid states are still rejected before querying.


def test_air_water_registry_ignore_pressure_arg():
    """Air/water primitives must stay value-identical whether or not P is
    passed (the 2D loop now forwards P to every primitive)."""
    from sjtu_tpmshx.models.fluid_props import FLUIDS
    for name in ('air', 'water'):
        m = FLUIDS[name]
        for fn in (m.cp, m.mu, m.k):
            assert fn(330.0) == fn(330.0, 5.0e5)         # P ignored, identical
