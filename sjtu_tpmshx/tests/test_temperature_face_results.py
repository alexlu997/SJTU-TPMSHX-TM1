"""Full CC metrics require their captured model-enthalpy advective boundary powers."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.metrics import evaluate
from sjtu_tpmshx.tests.test_conservative_energy_results import result_fixture


def temperature_fixture(dimension):
    old = result_fixture(dimension)
    flux = mutable_data(old.boundary_fluxes)
    powers = flux.pop('true_h')['boundary_power']
    ledger = dict(definition='model_enthalpy_temperature_v1', physical_dimension=dimension,
        physical_boundary_complete=True, power_units='W/m' if dimension == 2 else 'W',
        solved=dict(A=True, B=True, solid=True), advective_out=powers,
        diffusive_out={side: {face: np.full_like(values, 1000.) for face, values in planes.items()}
                       for side, planes in powers.items()})
    flux['temperature'] = ledger
    if dimension == 2:
        fine = mutable_data(ledger)
        for planes in fine['advective_out'].values():
            for face in planes:
                planes[face] *= 1.2
        flux['fine'] = dict(dx=old.grid['dx'], dy=old.grid['dy'], temperature=fine)
    metadata = mutable_data(old.metadata)
    metadata.update(thermal_mode='temperature', temperature_transport='model_enthalpy_temperature_v1')
    return replace(old, metadata=metadata, boundary_fluxes=flux)


@pytest.mark.parametrize('dimension', [2, 3])
def test_signed_advective_duty_survives_replay_without_fourier_or_velocity_reconstruction(tmp_path, monkeypatch, dimension):
    from sjtu_tpmshx.postprocess import metrics
    def forbidden(*args, **kwargs):
        pytest.fail('recorded CC boundary power must not use old cell velocity reduction')
    monkeypatch.setattr(metrics, '_enthalpy_balance_2d', forbidden)
    result = temperature_fixture(dimension)
    for source in (result, load_result(save_result(result, tmp_path / 'temperature.h5'))):
        actual = evaluate(source).metrics
        assert actual['Q'].value == pytest.approx(15.)
        assert actual['Q_A'].value == pytest.approx(15.)
        assert actual['Q_B'].value == pytest.approx(-15.)
        assert actual['energy_imbalance_rel'].value == pytest.approx(0., abs=1e-15)
        assert actual['Q'].spec.unit == ('W/m' if dimension == 2 else 'W')
        assert source.run_status['converged'] is False
        if dimension == 2:
            assert actual['Q_richardson_A'].value == pytest.approx(19.)
            assert actual['Q_richardson_B'].value == pytest.approx(19.)


@pytest.mark.parametrize('dimension', [2, 3])
def test_full_cc_h_driver_does_not_grant_model_h_optimization_qualification(dimension):
    from sjtu_tpmshx.optimization.multi_condition import _full_result_metadata
    result = temperature_fixture(dimension)
    metadata = mutable_data(result.metadata)
    metadata['native'] = dict(algorithm='model_h_tface_sou_fou_strict_v1' if dimension == 2
                             else 'model_h_tface_sou_sou_strict_v1')
    with pytest.raises(ValueError, match='requires full 2D/3D model_h results'):
        _full_result_metadata(replace(result, metadata=metadata))


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['missing_evidence', 'missing_declaration', 'definition', 'declaration', 'dimension',
    'units', 'incomplete', 'truthy_complete', 'prescribed_a', 'nan_a'])
def test_declared_temperature_transport_never_uses_legacy_reduction(tmp_path, dimension, defect):
    result = temperature_fixture(dimension)
    flux, metadata = mutable_data(result.boundary_fluxes), mutable_data(result.metadata)
    native = flux['temperature']
    status = 'invalid'
    if defect == 'missing_evidence':
        del flux['temperature'];status = 'insufficient_data'
    elif defect == 'missing_declaration':
        del metadata['temperature_transport']
    elif defect == 'definition':
        native['definition'] = 'mass_cp_temperature_v1'
    elif defect == 'declaration':
        metadata['temperature_transport'] = 'unknown'
    elif defect == 'dimension':
        native['physical_dimension'] = 3 if dimension == 2 else 2
    elif defect == 'units':
        native['power_units'] = 'W' if dimension == 2 else 'W/m'
    elif defect in ('incomplete', 'truthy_complete'):
        native['physical_boundary_complete'] = False if defect == 'incomplete' else 1
    elif defect == 'prescribed_a':
        native['solved']['A'] = False;status = 'unsupported'
    else:
        native['advective_out']['A']['x+'][0, 0] = np.nan
    altered = replace(result, metadata=metadata, boundary_fluxes=flux)
    for source in (altered, load_result(save_result(altered, tmp_path / 'invalid.h5'))):
        actual = evaluate(source).metrics
        assert actual['Q_A'].status == status
        assert actual['Q_A'].value is None
        if defect in ('prescribed_a', 'nan_a'):
            assert actual['Q_B'].value == pytest.approx(-15.)
        assert actual['T_out_A'].status == 'available'
        assert actual['mass_flow_A'].status == 'available'
