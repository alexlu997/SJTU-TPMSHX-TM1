"""Persisted strict full-3D controls must reach preparation without substitution."""
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.preprocess.three_d.preparation import _parse_geometry_inputs_3d_cfg


STRICT = dict(ltne_enthalpy_outer=1000, ltne_enthalpy_nsweep=25,
              ltne_enthalpy_omega=.6, ltne_enthalpy_tol=1e-6,
              ltne_enthalpy_coupled_energy_tol=1e-5,
              ltne_enthalpy_equation_energy_tol=1e-5,
              require_enthalpy_update_on_temperature=True)


def config(algorithm):
    cfg = ComputeConfig()
    cfg.geometry.Lz_m = .012
    cfg.solver.Nz = 3
    cfg.solver.enthalpy_algorithm = algorithm
    return cfg


@pytest.mark.parametrize('algorithm', ['legacy_h_fou', 'temperature_fou', 'temperature_sou'])
def test_strict_controls_survive_json_and_override_route_defaults(tmp_path, algorithm):
    cfg = config(algorithm)
    for key, value in STRICT.items():
        setattr(cfg.solver, key, value)
    cfg.validate_static_inputs()
    path = tmp_path / 'strict.json'
    cfg.to_json(path)
    restored = ComputeConfig.from_json(path)
    assert restored == cfg
    parsed = _parse_geometry_inputs_3d_cfg(restored)
    assert {key: parsed[key] for key in STRICT} == STRICT
    assert parsed['enthalpy_algorithm'] == algorithm
    assert parsed['enthalpy_temperature_tol_K'] == 1e-8
    assert parsed['ltne_enthalpy_tol'] != parsed['enthalpy_temperature_tol_K']


@pytest.mark.parametrize('algorithm,omega', [('legacy_h_fou', None), ('temperature_fou', .6), ('temperature_sou', .2)])
def test_unspecified_controls_keep_existing_preparation_defaults(algorithm, omega):
    cfg = config(algorithm)
    parsed = _parse_geometry_inputs_3d_cfg(cfg)
    if algorithm == 'legacy_h_fou':
        assert all(key not in parsed for key in STRICT)
    else:
        assert parsed['ltne_enthalpy_outer'] == 1500
        assert parsed['ltne_enthalpy_nsweep'] == 5
        assert parsed['ltne_enthalpy_omega'] == omega
        assert parsed['ltne_enthalpy_tol'] == 1e-3
        assert all(key not in parsed for key in (
            'ltne_enthalpy_coupled_energy_tol', 'ltne_enthalpy_equation_energy_tol',
            'require_enthalpy_update_on_temperature'))


@pytest.mark.parametrize('key,value', [
    ('ltne_enthalpy_outer', 0), ('ltne_enthalpy_nsweep', -1),
    ('ltne_enthalpy_outer', True), ('ltne_enthalpy_nsweep', 2.5),
    ('ltne_enthalpy_omega', 1.01), ('ltne_enthalpy_tol', 0.),
    ('ltne_enthalpy_coupled_energy_tol', float('nan')),
    ('ltne_enthalpy_equation_energy_tol', float('inf')),
    ('require_enthalpy_update_on_temperature', 1),
])
def test_invalid_control_is_rejected_before_preparation(key, value):
    cfg = config('temperature_sou')
    setattr(cfg.solver, key, value)
    with pytest.raises(ValueError, match=key):
        cfg.validate_static_inputs()


def test_explicit_three_dimensional_controls_are_not_silently_ignored_in_2d():
    cfg = ComputeConfig()
    cfg.solver.ltne_enthalpy_coupled_energy_tol = 1e-5
    with pytest.raises(ValueError, match='full 3D'):
        cfg.validate_static_inputs()
