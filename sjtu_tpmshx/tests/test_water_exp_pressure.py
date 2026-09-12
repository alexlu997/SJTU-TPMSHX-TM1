"""Water experiment Pa gauge boundary, without private workbook fixtures."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.validation.water_exp import with_water_absolute_pressures


@pytest.mark.parametrize('source', [
    'water-air_G7-t0p6_shanghai_experiment_20260401.xlsx',
    'water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx',
    'water-air_D7-t0p6_experiment_water-straight_20260609.xlsx',
    'water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx',
])
def test_convert_once_keep_raw_dp_and_duplicate_rows(source):
    raw = pd.DataFrame({'ti': [20., 20.], 'to': [25., 25.],
                        'pi': [-2000., -2000.], 'po': [-1950., -1950.],
                        'dp': [-50., -50.], 'mdot': [.08, .09]})
    kw = dict(source=Path('data/raw_data/experiments/water_air') / source, sheet='G_7_6',
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
    assert converted.attrs['water_pressure']['source'] == source
    with pytest.raises(ValueError, match='unconfirmed'):
        with_water_absolute_pressures(raw, **(kw | {'source': 'unconfirmed.xlsx'}))


@pytest.mark.parametrize('source', [
    'water-air_G7-t0p6_shanghai_experiment_20260401.xlsx',
    'water-air_G7-t0p6_shanghai_experiment_ports-swapped_20260407.xlsx',
    'water-air_D7-t0p6_experiment_water-straight_20260609.xlsx',
])
def test_canonical_loader_preserves_positions_and_adds_absolute(monkeypatch, source):
    from sjtu_tpmshx.validation.harness import _harness as loader
    raw = pd.DataFrame(np.zeros((2, 35)))
    raw[24], raw[25], raw[26], raw[27] = 20., 25., -2000., -1950.
    footer = pd.DataFrame(np.nan, index=[2, 3], columns=raw.columns)
    footer.loc[2, 12], footer.loc[3, 20] = -.56, 558.
    sheet = pd.concat([raw, footer])
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: sheet)
    result = loader.load_cases_df(Path('data/raw_data/experiments/water_air') / source)
    assert list(result.columns[:35]) == list(raw.columns)
    pd.testing.assert_frame_equal(result.iloc[:, :35], raw, check_exact=True,
                                  check_column_type=False)
    assert result.water_P_in_abs_Pa.tolist() == [99325., 99325.]
    pd.testing.assert_frame_equal(loader.load_cases_df(Path('unconfirmed.xlsx')), sheet)


@pytest.mark.parametrize('case_id', ['工况2', np.nan])
def test_canonical_loader_keeps_incomplete_cases_for_validation(monkeypatch, case_id):
    from sjtu_tpmshx.models.fluid_props import WaterStateError
    from sjtu_tpmshx.validation.harness import _harness as loader
    raw = pd.DataFrame(np.zeros((3, 35)))
    raw[0] = ['工况1', case_id, '工况3']
    raw[24], raw[25], raw[26], raw[27] = 20., 25., -2000., -1950.
    raw.loc[1, 24] = np.nan
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: raw)
    source = Path('water-air_G7-t0p6_shanghai_experiment_20260401.xlsx')
    with pytest.raises(WaterStateError, match='index=\\(1,\\)'):
        loader.load_cases_df(source)


def test_generic_absolute_config_is_not_converted():
    from sjtu_tpmshx.domain.compute_config import ComputeConfig, FluidConfig
    cfg = ComputeConfig(fluid_B=FluidConfig(type='water', P_in_Pa=200000.))
    cfg.validate()
    assert cfg.fluid_B.P_in_Pa == 200000.


def test_hx_loader_keeps_negative_dp_and_duplicate_records(monkeypatch):
    from sjtu_tpmshx.validation import hx_experiments as loader
    raw = pd.DataFrame({
        'case_name': ['工况1', '工况2'], '样机水流量kg/s': [.08, .09],
        '水进口温度/℃': [20., 20.], '水出口温度/℃': [25., 25.],
        '水进口压力/Pa': [-2000., -2000.], '水出口压力/Pa': [-1950., -1950.],
        '水侧压差/Pa': [-50., -50.],
    })
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: raw)
    converted = loader.load_water_cases('Gyroid')
    assert len(converted) == 2
    assert converted.dp_nonphysical.all() and converted.dup_row.all()
    pd.testing.assert_frame_equal(converted[raw.columns], raw)
    assert converted.water_P_in_abs_Pa.tolist() == [99325., 99325.]


def test_hx_air_reader_keeps_floor_and_duplicate_flags(monkeypatch):
    from sjtu_tpmshx.validation import hx_experiments as loader
    raw = pd.DataFrame({
        'case_name': ['工况1', '工况2', '工况3', '备注'],
        '样机空气流量kg/s': [.01, .02, .03, np.nan],
        '空气进口温度/℃': [20., 21., 21., np.nan],
        '空气出口温度/℃': [25., 26., 26., np.nan],
        '空气进口压力/Pa': [1500., 5000., 5000., np.nan],
        '空气出口压力/Pa': [1000., 1000., 1000., np.nan],
    })
    monkeypatch.setattr(loader.pd, 'read_excel', lambda *args, **kwargs: raw)
    d = loader.load_air_cases('Diamond')
    assert d.case.tolist() == ['工况1', '工况2', '工况3']
    assert d.dp_floor.tolist() == [True, False, False]
    assert d.dup_row.tolist() == [False, True, True]
    assert d.excluded.all()


def test_current_hx_tools_import_without_legacy_models():
    import subprocess
    import sys

    code = '''
import sys
for name in (
    'validation.df_refit.gamma_hx_air', 'validation.df_refit.gamma_hx_water',
    'validation.df_refit.gamma_specimen', 'df_surrogate.gamma_df',
    'df_surrogate.surrogate_v3', 'df_surrogate.smooth_df', 'df_surrogate.sco2_df',
):
    sys.modules['sjtu_tpmshx.' + name] = None
from sjtu_tpmshx.validation.df_refit import fit_experimental_effective, cf_cross_fluid
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[2], check=False)
    assert result.returncode == 0, result.stderr


def test_cross_fluid_collect_uses_raw_quality_members(monkeypatch):
    from sjtu_tpmshx.validation.df_refit import cf_cross_fluid as cf
    air = pd.DataFrame({
        'case': ['high-flow', 'floor'], 'excluded': [False, True],
        '样机空气流量kg/s': [1., .001], '空气进口温度/℃': [20., 20.],
        '空气出口温度/℃': [25., 25.], '空气进口压力/Pa': [50000., 1500.],
        '空气出口压力/Pa': [1000., 1000.],
    })
    water = pd.DataFrame({
        'case': ['good', 'negative'], 'dp_nonphysical': [False, True],
        'dup_row': [False, False], '样机水流量kg/s': [.08, .09],
        '水进口温度/℃': [20., 20.], '水出口温度/℃': [25., 25.],
        'water_P_in_abs_Pa': [110000., 110000.],
        'water_P_out_abs_Pa': [100000., 110050.], '水侧压差/Pa': [10000., -50.],
    })
    sco2 = pd.DataFrame(dict(case=[1], side=['hot'], ok_dp=[True],
                             mdot=[.1], rho=[400.], mu=[.00003], dP_MPa=[.01], Re=[5000.]))
    sco2.attrs['A_flow_m2'] = .0006
    monkeypatch.setattr(cf, 'load_air_cases', lambda tp: air)
    monkeypatch.setattr(cf, 'load_water_cases', lambda tp: water)
    monkeypatch.setattr(cf, 'load_exp', lambda tp: sco2)
    d = cf.collect()
    assert set(zip(d.fluid, d.topo, d.case)) == {
        (fluid, topo, case) for topo in ('Diamond', 'Gyroid')
        for fluid, case in [('air', 'high-flow'), ('water', 'good'), ('sco2', '1')]}
    assert len(d) == 6
    assert np.isfinite(d.cF_meas).all()


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
