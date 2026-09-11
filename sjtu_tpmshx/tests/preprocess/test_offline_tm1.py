"""Offline I/O/calibration behavior uses artificial data, never new physics evidence."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from sjtu_tpmshx.preprocess.offline import load_experiments, publish_surrogate
from sjtu_tpmshx.df_surrogate.surrogate_v3 import (
    SurrogateV3, P_ATM, R_AIR, K_S_CELLS, air_viscosity,
)


def test_explicit_clean_fit_publish_and_reload(tmp_path):
    source = tmp_path / 'artificial-training.xlsx'
    geometries = [(4., .3), (4., .5), (5., .4), (6., .3), (6., .5), (8., .4)]
    rows = []
    temperature = 298.15
    for length, thickness in geometries:
        for velocity in (5., 10., 15.):
            row = [0.] * 49
            flux = 1.2 * velocity
            lhs = air_viscosity(temperature) * flux / 1e-8 + 500. * flux**2
            dp = np.sqrt(P_ATM**2 + 2 * R_AIR * temperature * K_S_CELLS * length * 1e-3 * lhs) - P_ATM
            for column, value in {1: length, 2: thickness, 3: 2000., 7: 25.,
                                  9: air_viscosity(temperature), 12: 1.2,
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
    with pytest.raises(ValueError, match='Shanghai keyword'):
        publish_surrogate(forbidden, tmp_path / 'forbidden', data_revision='test')
    assert not (tmp_path / 'forbidden').exists()
    manifest = publish_surrogate(source, tmp_path / 'published', data_revision='artificial-test-v1')
    report = json.loads(manifest.read_text())
    assert report['data_revision'] == 'artificial-test-v1'
    assert report['source_workbook'] == str(source.resolve())
    assert report['pressure_basis'] == 'col43_alpha'
    for topology, entry in report['models'].items():
        assert entry['geometries'] == 6
        fitted = SurrogateV3(topology, training_workbook=source)
        loaded = SurrogateV3(topology, calibration_csv=manifest.parent / entry['file'])
        np.testing.assert_allclose(loaded._fit_K, 1e-8, rtol=1e-10)
        np.testing.assert_allclose(loaded._fit_cF, 500., rtol=1e-10)
        np.testing.assert_allclose(loaded.predict(5., .4), fitted.predict(5., .4), rtol=1e-12)
    with pytest.raises(FileExistsError):
        publish_surrogate(source, manifest.parent, data_revision='artificial-test-v1')


def test_missing_explicit_training_never_falls_back(tmp_path):
    with pytest.raises(FileNotFoundError):
        publish_surrogate(tmp_path / 'missing.xlsx', tmp_path / 'output', data_revision='test')
    assert not (tmp_path / 'output').exists()
    with pytest.raises(ValueError, match='revision'):
        publish_surrogate(tmp_path / 'missing.xlsx', tmp_path / 'output', data_revision='')
    with pytest.raises(ValueError, match='not both'):
        SurrogateV3(training_workbook=tmp_path / 'x', calibration_csv=tmp_path / 'y')


@pytest.mark.parametrize('length,thickness', [(7., .4), (6., .6)])
def test_training_rejects_held_out_geometry(tmp_path, length, thickness):
    source = tmp_path / 'training.xlsx'
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([['synthetic', 1.]]).to_excel(
            writer, sheet_name='边界效应系数', header=False, index=False)
        for topology in ('Diamond', 'Gyroid'):
            pd.DataFrame([['held-out', length, thickness]]).to_excel(
                writer, sheet_name=topology + '_汇总', index=False)
    for topology in ('Diamond', 'Gyroid'):
        with pytest.raises(ValueError, match='Shanghai'):
            SurrogateV3(topology, training_workbook=source)
    with pytest.raises(ValueError, match='Shanghai'):
        publish_surrogate(source, tmp_path / 'output', data_revision='test')
    assert not (tmp_path / 'output').exists()


def test_ordinary_full_preparation_never_reads_training(monkeypatch):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg

    def forbidden(*args, **kwargs):
        raise AssertionError('ordinary Case preparation attempted offline training')

    monkeypatch.setattr(pd, 'read_excel', forbidden)
    monkeypatch.setattr(SurrogateV3, '_build', forbidden)
    for dimension, config in ((2, baseline_config()), (3, _small_air_cfg())):
        case = prepare_case(config, case_id=f'offline-independent-{dimension}')
        assert case.grid['dimension'] == dimension


def test_existing_nu_fit_with_artificial_data():
    from sjtu_tpmshx.preprocess.offline import fit_nu_sco2
    from sjtu_tpmshx.validation.sco2_cfd.fit_nu_sco2 import _fit
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
    from sjtu_tpmshx.preprocess.offline import load_water, load_core, load_segments
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
