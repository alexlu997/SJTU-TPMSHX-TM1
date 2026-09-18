"""Option B (solve-in-enthalpy) 1D LTNE conservation PoC test.

The historical temperature-form 3D kernel telescoped a face-shared flux
F = ε·ρcp·u·A and convected T, conserving the ρcp·T "energy", which equals enthalpy
ONLY for constant cp. For sCO2 (cp spikes ×10-56 near the pseudocritical line)
ρcp·u·T ≠ ρu·h; the historical imbalance was ~41% on the 703 recuperator.
The enthalpy form (Option B) makes h the primary fluid unknown,
so the convection telescopes the true enthalpy flux ṁ·h.

This 1D PoC proves the enthalpy form conserves (A/B imbalance < 1%) on a
variable-cp CO2 counterflow case where the legacy cp·T form does not.
The production enthalpy implementation is now in solvers/ltne_enthalpy_3d.py;
test_ltne_enthalpy_3d.py checks its 3D behavior separately. This test retains
the PoC formulation comparison and does not replace those production checks.
"""
import pytest

try:
    from CoolProp.CoolProp import PropsSI as _PropsSI  # noqa: F401
    _HAVE_CP = True
except Exception:
    _HAVE_CP = False

pytestmark = pytest.mark.skipif(not _HAVE_CP, reason="CoolProp required")


def test_enthalpy_form_conserves_where_cpT_fails():
    """On a variable-cp CO2 counterflow straddling the pseudocritical line:
    legacy cp·T transport leaves a sizeable A/B enthalpy imbalance; the Option B
    enthalpy transport closes it to < 1%."""
    from sjtu_tpmshx.tests import enthalpy_1d_reference as m

    s = m.make_setup_sco2()

    # Historical ρcp·u·T transport retained as the comparison control:
    res_cpT = m.solve_cpT(s)
    met_cpT = m.compute_metrics(res_cpT, s)

    # Option B: enthalpy is the primary fluid unknown, convection carries ṁ·h.
    res_h = m.solve_enthalpy(s)
    met_h = m.compute_metrics(res_h, s)

    # The case must actually stress variable cp (else the test proves nothing).
    assert met_cpT["AB_imbal"] > 0.03, (
        f"setup does not stress variable cp: cp·T imbalance only "
        f"{met_cpT['AB_imbal']*100:.2f}% — push more flow through the spike")

    # Option B conserves true enthalpy across the two streams.
    assert met_h["AB_imbal"] < 0.01, (
        f"Option B enthalpy form not conserving: A/B imbalance "
        f"{met_h['AB_imbal']*100:.2f}% (cp·T baseline "
        f"{met_cpT['AB_imbal']*100:.2f}%)")

    # And it must be a clear improvement over cp·T on the same case.
    assert met_h["AB_imbal"] < 0.25 * met_cpT["AB_imbal"]


def test_enthalpy_form_recovers_solid_balance():
    """Option B: each stream's boundary enthalpy duty matches the volumetric
    solid exchange it sees (|Q_enth| ≈ |Q_solid|), to a few percent."""
    from sjtu_tpmshx.tests import enthalpy_1d_reference as m

    s = m.make_setup_sco2()
    met = m.compute_metrics(m.solve_enthalpy(s), s)

    assert met["e_imb_LTNE"] < 0.01, (
        f"solid LTNE balance Q_sA+Q_sB not closing: {met['e_imb_LTNE']*100:.3f}%")
    assert met["diff_A"] < 0.05 and met["diff_B"] < 0.05, (
        f"stream duty vs solid flux mismatch: A {met['diff_A']*100:.1f}% / "
        f"B {met['diff_B']*100:.1f}%")
