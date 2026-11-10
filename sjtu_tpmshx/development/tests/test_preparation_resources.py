"""Fixed preparation data retain their original values and separate windows."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from engineering.scripts.generate_native_model_coefficients import df_header
from sjtu_tpmshx.shared.configs import model_parameters as resources
from sjtu_tpmshx.development.tests import df_reference as reference


def test_preparation_data_match_frozen_corrections_and_domain():
    data = resources.load_preparation_df_parameters()
    assert tuple(data['domain']['L_nodes_mm']) == reference._L_NODES
    assert tuple(data['domain']['t_nodes_mm']) == reference._T_NODES
    for topology in ('Diamond', 'Gyroid'):
        np.testing.assert_array_equal(data['air_specimen']['sf'][topology], reference._AIR_SF[topology])
    np.testing.assert_array_equal(data['air_specimen']['t_nodes_mm'], reference._AIR_T)
    hx = data['hx']
    for fluid in ('air', 'water', 'sco2'):
        for topology in ('Diamond', 'Gyroid'):
            key = (fluid, topology)
            assert hx['sf'][fluid][topology] == reference._HX_SF[key]
            assert tuple(hx['calibration_u_mps'][fluid][topology]) == reference._HX_U_BOUNDS[key]
            assert tuple(hx['application_u_mps'][fluid][topology]) == reference._HX_APPLICATION_U_BOUNDS[key]
            expected = (reference._GYROID_AIR_RUNTIME_CALIBRATION_U if key == ('air', 'Gyroid')
                        else reference._HX_U_BOUNDS[key])
            assert tuple(hx['runtime_u_mps'][fluid][topology]) == expected
    assert hx['application_scope'] == reference._HX_APPLICATION_SCOPE
    assert hx['gyroid_air_calibration'] == reference._GYROID_AIR_CALIBRATION
    hx['sf']['air']['Gyroid'] = 0.
    assert resources.load_preparation_df_parameters()['hx']['sf']['air']['Gyroid'] > 0.


@pytest.mark.parametrize('path,value', [
    (('method',), 'unknown'), (('domain', 'L_nodes_mm'), [4., 5., 6., 8., 7.]),
    (('domain', 't_nodes_mm'), [.3, .4]), (('bracket_relative_tolerance',), True),
    (('hx', 'sf', 'air', 'Gyroid'), 0.),
    (('hx', 'runtime_u_mps', 'air', 'Gyroid'), [float('nan'), 23.]),
    (('hx', 'application_scope'), ''), (('hx', 'gyroid_air_calibration'), {})])
def test_preparation_resource_rejects_invalid_fixed_data(tmp_path, monkeypatch, path, value):
    data = resources.load_preparation_df_parameters()
    parent = data
    for name in path[:-1]:
        parent = parent[name]
    parent[path[-1]] = value
    (tmp_path/'preparation_df_v1.json').write_text(json.dumps(data))
    monkeypatch.setattr(resources, 'files', lambda _: tmp_path)
    with pytest.raises(ValueError):
        resources.load_preparation_df_parameters()


@pytest.mark.parametrize('change', ['missing-column', 'duplicate', 'off-grid', 'nonfinite', 'missing-node'])
def test_native_generator_rejects_bad_csv_before_build(tmp_path, change):
    path = Path(reference.TABLE_PATH)
    with path.open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        fields, rows = list(reader.fieldnames), list(reader)
    if change == 'missing-column':
        fields.remove('K_m2')
        rows = [{key: value for key, value in row.items() if key != 'K_m2'} for row in rows]
    elif change == 'duplicate':
        rows.append(rows[0].copy())
    elif change == 'off-grid':
        rows[0]['L_mm'] = '4.01'
    elif change == 'nonfinite':
        rows[0]['cF_fixed_1_m'] = 'nan'
    else:
        rows.pop()
    selected = tmp_path/'selected.csv'
    with selected.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError):
        df_header(selected)
