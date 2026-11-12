"""Model data must load without a numerical runtime or shared mutable state."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sjtu_tpmshx.shared.configs import model_parameters as resources


def test_model_parameters_have_independent_ownership():
    first = resources.load_model_parameters()
    first['nu']['air_coefficients']['Diamond']['c'] = -1.
    first['geometry']['level_set_coefficients']['Diamond'][0] = -1.
    second = resources.load_model_parameters()
    assert second['nu']['air_coefficients']['Diamond']['c'] == .0944
    assert second['geometry']['level_set_coefficients']['Diamond'] == [
        4.804355187041238, -2.0288570445530025]
    assert second['envelope']['r_air_default'] == 287.05
    assert second['constants']['gas_constant'] / second['constants']['air_molar_mass'] != 287.05


@pytest.mark.parametrize('section,key,value', [
    (None, 'schema_version', 'unknown'),
    (None, 'geometry', None),
    ('constants', 'gas_constant', True),
    ('constants', 'gas_constant', float('nan')),
    ('constants', 'gas_constant', 0.),
    ('air', 'cp_coefficients', [1., 2.]),
    ('air', 'temperature_range_K', [1100., 200.]),
    ('nu', 'air_coefficients', {'Diamond': {'c': 1., 'a': 1., 'd': 1.}}),
    ('geometry', 'solid_tortuosity', {'Diamond': [1., 2.], 'Gyroid': [1.]}),
    ('co2_application', 'version', ''),
])
def test_model_resource_rejects_invalid_data(tmp_path, monkeypatch, section, key, value):
    data = resources.load_model_parameters()
    (data if section is None else data[section])[key] = value
    (tmp_path / 'model_parameters_v1.json').write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(resources, 'files', lambda _: tmp_path)
    with pytest.raises(ValueError):
        resources.load_model_parameters()


def test_quick_design_defaults_keep_values_types_and_independent_ownership():
    data = resources.load_quick_design_parameters()
    assert data == {
        'k_s': 16.0, 'nx': 60, 'tol': 1e-5, 'geometry_resolution': 128,
        'arrangements': {
            'cross': dict(dirB=2, ny=40, nz=1, alpha=.7, maxit=8000, qtol=1e-4, chunk=100),
            'counter': dict(dirB=1, ny=1, nz=2, alpha=.3, maxit=20000, qtol=None, chunk=None),
        },
    }
    assert type(data['k_s']) is float and type(data['tol']) is float
    for row in data['arrangements'].values():
        assert type(row['alpha']) is float
        assert all(type(row[key]) is int for key in ('dirB', 'ny', 'nz', 'maxit'))
    data['arrangements']['counter']['chunk'] = 250
    assert resources.load_quick_design_parameters()['arrangements']['counter']['chunk'] is None


@pytest.mark.parametrize('path,value', [
    (('nx',), True), (('geometry_resolution',), 128.0),
    (('k_s',), 0.), (('tol',), float('nan')), (('arrangements',), {}),
    (('arrangements', 'cross', 'dirB'), 1), (('arrangements', 'cross', 'ny'), 0),
    (('arrangements', 'cross', 'alpha'), 1.1), (('arrangements', 'cross', 'maxit'), False),
    (('arrangements', 'cross', 'qtol'), float('inf')),
    (('arrangements', 'counter', 'chunk'), 250.5),
])
def test_quick_design_resource_rejects_invalid_defaults(tmp_path, monkeypatch, path, value):
    data = resources.load_model_parameters()
    row = data['quick_design']
    for name in path[:-1]:
        row = row[name]
    row[path[-1]] = value
    (tmp_path / 'model_parameters_v1.json').write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(resources, 'files', lambda _: tmp_path)
    with pytest.raises(ValueError, match='quick_design'):
        resources.load_quick_design_parameters()


def test_quick_design_catalog_checks_versions_and_returns_owned_defaults():
    from sjtu_tpmshx.shared.domain.model_refs import ModelRef
    from sjtu_tpmshx.shared.models.catalog import resolve_model

    version = resources.MODEL_VERSIONS['quick_design']
    model = ModelRef('quick_design', version, {})
    first = resolve_model(model)
    assert first == resources.load_quick_design_parameters()
    first['arrangements']['counter']['qtol'] = 0.1
    assert resolve_model(model)['arrangements']['counter']['qtol'] is None
    with pytest.raises(ValueError, match='unknown model resource'):
        resolve_model(ModelRef('quick_design', 'unknown', {}))
    with pytest.raises(ValueError, match='takes no fixed parameters'):
        resolve_model(ModelRef('quick_design', version, {'nx': 1}))


def test_native_coefficient_generation_needs_only_standard_library():
    root = Path(__file__).resolve().parents[3]
    probe = subprocess.run([sys.executable, '-S', '-c', '''
import sys
from engineering.scripts.generate_native_model_coefficients import header, df_header
text = header()
assert 'inline constexpr double gas_constant = 8.314;' in text
assert 'model_h_air{{1004.5, 0.172, -7.56e-05, 273.15, 300.0}};' in text
assert 'model_h_water{{4182.0, 0.0, 0.0, 273.15, 300.0}};' in text
assert 'inline constexpr double quick_design_k_s = 16.0;' in text
assert 'inline constexpr double quick_design_tol = 1e-05;' in text
assert 'inline constexpr std::size_t quick_design_nx = 60;' in text
assert 'inline constexpr std::size_t quick_design_geometry_resolution = 128;' in text
assert 'inline constexpr int quick_design_cross_dir_b{2};' in text
assert 'inline constexpr std::size_t quick_design_cross_ny{40};' in text
assert 'inline constexpr double quick_design_cross_alpha{0.7};' in text
assert 'inline constexpr std::size_t quick_design_cross_maxit{8000};' in text
assert 'inline constexpr std::optional<double> quick_design_cross_qtol{0.0001};' in text
assert 'inline constexpr std::optional<std::size_t> quick_design_cross_chunk{100};' in text
assert 'inline constexpr int quick_design_counter_dir_b{1};' in text
assert 'inline constexpr std::size_t quick_design_counter_nz{2};' in text
assert 'inline constexpr double quick_design_counter_alpha{0.3};' in text
assert 'inline constexpr std::size_t quick_design_counter_maxit{20000};' in text
assert 'inline constexpr std::optional<double> quick_design_counter_qtol{std::nullopt};' in text
assert 'inline constexpr std::optional<std::size_t> quick_design_counter_chunk{std::nullopt};' in text
df = df_header()
from sjtu_tpmshx.shared.configs.model_parameters import MODEL_VERSIONS
for name, version in MODEL_VERSIONS.items():
    assert f'inline constexpr char {name}_version[] = \"{version}\";' in text
assert 'namespace tpmshx::preparation::df_data' in df
assert 'cfd_full_core_3cell_fixed_v2' in df
assert 'inline constexpr double df_values[2][5][4][2]' in df
assert not any(name.startswith(('numpy', 'scipy', 'CoolProp', 'sjtu_tpmshx.shared.models',
                                'sjtu_tpmshx.solvers')) for name in sys.modules)
'''], cwd=root, capture_output=True, text=True, timeout=60)
    assert probe.returncode == 0, probe.stdout + probe.stderr


def test_co2_resource_preserves_values_and_selected_path(tmp_path):
    data = resources.load_co2_coefficients()
    assert data['bounds']['Re'] == [3000., 60000.]
    assert data['topologies']['Diamond']['Nu']['parameters']['theta'] == [
        5.116529451028265, .7145279830193259, .3962239747502244,
        -.13822384274620997, .037642668209224774]
    selected = tmp_path / 'coefficients.json'
    data['segment'] = 1
    selected.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='resource/version mismatch'):
        resources.load_co2_coefficients(selected)


@pytest.mark.parametrize('bounds', [[3000.], [60000., 3000.], [0., 60000.],
                                   [3000., float('nan')], [3000., float('inf')]])
def test_co2_resource_checks_authoritative_re_bounds(tmp_path, bounds):
    data = resources.load_co2_coefficients()
    data['bounds']['Re'] = bounds
    selected = tmp_path / 'coefficients.json'
    selected.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='CO2 bounds.Re'):
        resources.load_co2_coefficients(selected)


@pytest.mark.parametrize('theta', [[None, 0., 0., 0., 0.], [[0.]] * 5,
                                  [float('nan'), 0., 0., 0., 0.]])
def test_co2_selected_path_keeps_invalid_theta_error(tmp_path, monkeypatch, theta):
    from sjtu_tpmshx.shared.models import co2_correlations

    data = resources.load_co2_coefficients()
    data['topologies']['Diamond']['Nu']['parameters']['theta'] = theta
    selected = tmp_path / 'coefficients.json'
    selected.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(co2_correlations, 'DATA_PATH', selected)
    co2_correlations.coefficients.cache_clear()
    try:
        for read in (lambda: resources.load_co2_coefficients(selected),
                     co2_correlations.coefficients):
            with pytest.raises(ValueError, match='^CO2 Nu requires five finite coefficients$'):
                read()
    finally:
        co2_correlations.coefficients.cache_clear()
