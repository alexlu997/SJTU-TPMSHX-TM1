"""The new Excel check must use historical mdot and developed-cell Nu."""
import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.cases import validate_water_nu_excel as validator


def test_current_basis_ignores_legacy_velocity_and_full_core_nu(monkeypatch):
    raw = pd.DataFrame(dict(
        geometry_id=['D_7_6'], lattice=['D'], cell_size_mm=[10.],
        wall_thickness_mm=[6.], rho_kg_m3=[1000.], mu_Pa_s=[.001],
        cp_J_kgK=[4200.], k_W_mK=[.6], Dh_m=[.001], mdot_in_kg_s=[.01],
        Core2_Nu=[20.], Core3_Nu=[40.], Core1_Nu=[1000.],
        Nu_core=[1000.], Um_m_s=[123.]))
    # A known geometry isolates the units/reduction from the geometry algorithm.
    monkeypatch.setattr(validator, '_attach_geometry', lambda d, topo:
                        d.assign(L_mm=10., eps_f=.25, Dh_cfd_m=d.Dh_m, Dh_m=.002))
    d = validator.evaluate(raw)
    assert len(d) == 1
    assert d.u_current_m_s.iloc[0] == pytest.approx(.4)
    assert d.Re_current.iloc[0] == pytest.approx(800.)
    assert d.Pr_current.iloc[0] == pytest.approx(7.)
    assert d.Nu_ref.iloc[0] == pytest.approx(60.)
    changed = validator.evaluate(raw.assign(Um_m_s=999., Nu_core=9999., Core1_Nu=9999.))
    pd.testing.assert_frame_equal(d[['Nu_ref', 'Nu_pred']], changed[['Nu_ref', 'Nu_pred']])
    with pytest.raises(ValueError, match='invalid required numeric data'):
        validator.evaluate(raw.assign(Core3_Nu=np.nan))


def test_accuracy_gate_rejects_either_error_without_rounding():
    assert validator.accepted(dict(rmsre=.10, bias=-.05))
    assert not validator.accepted(dict(rmsre=.100001, bias=0.))
    assert not validator.accepted(dict(rmsre=.09, bias=-.050001))
