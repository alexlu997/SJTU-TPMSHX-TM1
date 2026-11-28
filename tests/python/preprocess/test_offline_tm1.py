"""Offline I/O/calibration behavior uses artificial data, never new physics evidence."""
import shutil

import numpy as np
import pandas as pd
import pytest

from tm1.preprocess.offline import load_experiments


def test_explicit_cleaning_and_source_guard(tmp_path):
    source = tmp_path / 'artificial-training.xlsx'
    geometries = [(4., .3), (4., .5), (5., .4), (6., .3), (6., .5), (8., .4)]
    rows = []
    for length, thickness in geometries:
        for velocity in (5., 10., 15.):
            row = [0.] * 49
            dp = velocity * 100.
            for column, value in {1: length, 2: thickness, 3: 2000., 7: 25.,
                                  9: 1.8e-5, 12: 1.2,
                                  13: velocity, 43: dp, 47: .9 * dp}.items():
                row[column] = value
            rows.append(row)
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([['synthetic', 1.]]).to_excel(writer, sheet_name='边界效应系数', header=False, index=False)
        for topology in ('Diamond', 'Gyroid'):
            frame = pd.DataFrame(rows)
            frame[0] = [f'{topology[0]}_{int(row[1])}_{int(row[2] * 10):02d}' for row in rows]
            frame.to_excel(writer, sheet_name=topology + '_汇总', header=True, index=False)
    cleaned = load_experiments(source=source)
    assert len(cleaned) == 36
    np.testing.assert_allclose(cleaned['dP_Pa'].iloc[:18], np.array(rows)[:, 47])
    assert (cleaned['r_h_m'] > 0).all()
    forbidden = tmp_path / 'shanghai.xlsx'
    shutil.copyfile(source, forbidden)
    with pytest.raises(ValueError, match='Shanghai keyword'):
        load_experiments(source=forbidden)
    with pytest.raises(FileNotFoundError):
        load_experiments(source=tmp_path / 'missing.xlsx')


def test_ordinary_full_preparation_never_reads_training(monkeypatch):
    from tm1.preprocess.api import prepare_case
    from tests.python.integration_tm1.integration_support import baseline_config
    from tests.python.cases_3d import small_air_config

    def forbidden(*args, **kwargs):
        raise AssertionError('ordinary Case preparation attempted offline training')

    monkeypatch.setattr(pd, 'read_excel', forbidden)
    for dimension, config in ((2, baseline_config()), (3, small_air_config())):
        case = prepare_case(config, case_id=f'offline-independent-{dimension}')
        assert case.grid['dimension'] == dimension


def test_existing_nu_fit_with_artificial_data():
    from tm1.preprocess.offline import fit_nu_sco2
    from tm1.development.validation.sco2_cfd.fit_nu_sco2 import _fit
    assert _fit is fit_nu_sco2
    re = np.array([1000., 2000., 4000., 8000.])
    pr = np.array([1., 2., 4., 1.5])
    data = pd.DataFrame(dict(Re_b=re, Pr_b=pr, Dh_m=.002, L_mm=5.,
                             rho_w=1., rho_b=1., cp_bar=1., cp_b=1.,
                             mu_w=1., mu_b=1., Nu_b=.3 * re**.75 * pr**(1 / 3)))
    fitted = fit_nu_sco2(data, ['re', 'pr'], fixed={'pr': 1 / 3})
    np.testing.assert_allclose([fitted['c'], fitted['a'], fitted['b']],
                               [.3, .75, 1 / 3], rtol=1e-12)


def test_explicit_water_input_retains_raw_geometry_and_flags(tmp_path):
    from tm1.preprocess.offline import load_water, load_core, load_segments
    source = tmp_path / 'artificial-water.xlsx'
    pd.DataFrame([dict(geometry_id='D_7_3', cell_size_mm=7., wall_thickness_mm=3.,
                       Dh_m=.003, Re=1234., rho_kg_m3=1000., mu_Pa_s=.001,
                       k_W_mK=.6, Um_m_s=1., cp_J_kgK=4200., dp_core_Pa=100.,
                       core_length_m=.021, h_core_W_m2K=100., Core2_Nu=2.,
                       Core3_Nu=4.)]).to_excel(source, index=False)
    clean = load_water('Diamond', source=source)
    assert len(clean) == 1 and clean.iloc[0]['flow_suspect']
    assert clean.iloc[0]['Dh_cfd_m'] == .003
    assert clean.iloc[0]['Re_nominal'] == 1234.
    np.testing.assert_allclose(clean.iloc[0]['Nu_dev'],
                               3. * clean.iloc[0]['Dh_m'] / .003)
    for loader in (load_core, load_segments):
        with pytest.raises(ValueError, match='lattice'):
            loader('unknown', source=tmp_path / 'missing.csv')
