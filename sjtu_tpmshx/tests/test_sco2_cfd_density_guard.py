"""Reference-state de-duplication must still validate every uploaded density."""
import numpy as np
import pandas as pd
import pytest
from CoolProp.CoolProp import PropsSI

from sjtu_tpmshx.df_surrogate import load_sco2_cfd as loader


@pytest.mark.parametrize('load', [loader.load_core, loader.load_segments])
@pytest.mark.parametrize('reverse', [False, True])
def test_loader_rejects_later_conflicting_density_before_geometry(tmp_path, monkeypatch, load, reverse):
    density = PropsSI('D', 'T', 307.82, 'P', 8e6, 'CO2')
    frame = pd.DataFrame(dict(Tref=[307.82, 307.82], rho_kg_m3=[density, 2*density]))
    path = tmp_path / 'uploaded.csv'
    (frame.iloc[::-1] if reverse else frame).to_csv(path, index=False)
    monkeypatch.setattr(loader, '_attach_geometry',
                        lambda *a: pytest.fail('unverified density reached geometry/fit inputs'))
    with pytest.raises(ValueError, match='Pressure-map guard'):
        load('Diamond', source=path)


def test_guard_evaluates_unique_states_but_checks_all_rows(monkeypatch):
    import CoolProp.CoolProp as coolprop
    actual = coolprop.PropsSI
    calls = []
    def observed(*args):
        calls.append((np.asarray(args[2]).copy(), np.asarray(args[4]).copy()))
        return actual(*args)
    temperatures = np.array([327.12, 307.82, 327.12, 307.82])
    pressures = np.array([12e6, 8e6, 12e6, 8e6])
    densities = actual('D', 'T', temperatures, 'P', pressures, 'CO2')
    frame = pd.DataFrame(dict(Tref=temperatures, P_Pa=pressures, rho_kg_m3=densities),
                         index=[4, 1, 4, 1])  # Row labels are not a mapping key.
    monkeypatch.setattr(coolprop, 'PropsSI', observed)
    loader._verify_rho_guard(frame)
    assert len(calls) == 1 and len(calls[0][0]) == 2
    frame.iloc[-1, frame.columns.get_loc('rho_kg_m3')] *= 2
    with pytest.raises(ValueError, match='Pressure-map guard'):
        loader._verify_rho_guard(frame)


@pytest.mark.parametrize('density', [float('nan'), float('inf'), 0., -1.])
def test_invalid_reference_density_cannot_bypass_relative_guard(density):
    valid = PropsSI('D', 'T', 307.82, 'P', 8e6, 'CO2')
    frame = pd.DataFrame(dict(Tref=[307.82, 307.82], P_Pa=[8e6, 8e6],
                              rho_kg_m3=[valid, density]))
    with pytest.raises(ValueError, match='reference density'):
        loader._verify_rho_guard(frame)
