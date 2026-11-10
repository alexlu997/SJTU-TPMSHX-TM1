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


def test_native_coefficient_generation_needs_only_standard_library():
    root = Path(__file__).resolve().parents[3]
    probe = subprocess.run([sys.executable, '-S', '-c', '''
import sys
from engineering.scripts.generate_native_model_coefficients import header
text = header()
assert 'inline constexpr double gas_constant = 8.314;' in text
assert 'model_h_air{{1004.5, 0.172, -7.56e-05, 273.15, 300.0}};' in text
assert 'model_h_water{{4182.0, 0.0, 0.0, 273.15, 300.0}};' in text
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
