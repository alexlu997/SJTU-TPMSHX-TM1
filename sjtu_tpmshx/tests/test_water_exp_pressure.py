"""Water experiment Pa gauge boundary, without private workbook fixtures."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.water_exp import with_water_absolute_pressures


def test_convert_once_keep_raw_dp_and_duplicate_rows():
    raw = pd.DataFrame({'ti': [20., 20.], 'to': [25., 25.],
                        'pi': [-2000., -2000.], 'po': [-1950., -1950.],
                        'dp': [-50., -50.], 'mdot': [.08, .09]})
    kw = dict(source='7-6-Water-dp.xlsx', sheet='G_7_6',
              tin='ti', tout='to', pin='pi', pout='po')
    converted = with_water_absolute_pressures(raw, **kw)
    pd.testing.assert_frame_equal(converted[raw.columns], raw)
    assert converted.water_P_in_abs_Pa.tolist() == [99325., 99325.]
    assert converted.water_P_out_abs_Pa.tolist() == [99375., 99375.]
    np.testing.assert_array_equal(converted.water_P_in_abs_Pa
                                  - converted.water_P_out_abs_Pa, raw.dp)
    again = with_water_absolute_pressures(converted, **kw)
    pd.testing.assert_frame_equal(again, converted)
    assert converted.attrs['water_pressure']['raw_unit'] == 'Pa'
    assert converted.attrs['water_pressure']['atmosphere_measured'] is False
    assert converted.attrs['water_pressure']['source'] == kw['source']
    with pytest.raises(ValueError, match='unconfirmed'):
        with_water_absolute_pressures(raw, **(kw | {'source': 'unconfirmed.xlsx'}))


def test_canonical_loader_preserves_positions_and_adds_absolute(monkeypatch):
    from sjtu_tpmshx.validation.harness import _harness as loader
    raw = pd.DataFrame(np.zeros((2, 35)))
    raw[24], raw[25], raw[26], raw[27] = 20., 25., -2000., -1950.
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: raw)
    result = loader.load_cases_df(Path('20260401-上海电气天然气加热器实验工况.xlsx'))
    assert list(result.columns[:35]) == list(raw.columns)
    np.testing.assert_array_equal(result.iloc[:, :35].to_numpy(), raw.to_numpy())
    assert result.water_P_in_abs_Pa.tolist() == [99325., 99325.]
    pd.testing.assert_frame_equal(loader.load_cases_df(Path('unconfirmed.xlsx')), raw)


def test_generic_absolute_config_is_not_converted():
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig
    cfg = ComputeConfig(fluid_B=FluidConfig(type='water', P_in_Pa=200000.))
    cfg.validate()
    assert cfg.fluid_B.P_in_Pa == 200000.


def test_hx_loader_keeps_negative_dp_and_duplicate_records(monkeypatch):
    from sjtu_tpmshx.validation.df_refit import gamma_hx_water as loader
    raw = pd.DataFrame({
        'case_name': ['工况1', '工况2'], '样机水流量kg/s': [.08, .09],
        '水进口温度/℃': [20., 20.], '水出口温度/℃': [25., 25.],
        '水进口压力/Pa': [-2000., -2000.], '水出口压力/Pa': [-1950., -1950.],
        '水侧压差/Pa': [-50., -50.],
    })
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: raw)
    converted = loader._load_cases('Gyroid')
    assert len(converted) == 2
    assert converted.dp_nonphysical.all() and converted.dup_row.all()
    pd.testing.assert_frame_equal(converted[raw.columns], raw)
    assert converted.water_P_in_abs_Pa.tolist() == [99325., 99325.]


def test_pricing_config_uses_absolute_pressure_preserving_mass_flow():
    from sjtu_tpmshx.validation.cases.price_f2_convergence_3d import _build_cfg, SPEC
    from sjtu_tpmshx.models.tpms_props import water_density
    row = {i: 0. for i in range(34)}
    row.update({5: .05, 7: .1, 24: 20., 28: 150., 30: 3000.})
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 99325.
    cfg = _build_cfg(0, df, 8, 4, 3, mode='f2', mom_tol=1e-4,
                     mass_local_tol=1e-4, mass_global_tol=1e-4)
    assert cfg.fluid_B.P_in_Pa == 99325.
    assert (cfg.fluid_B.u_mps * water_density(cfg.fluid_B.T_in_K)
            * SPEC.a_flow_m2) == pytest.approx(.1)
