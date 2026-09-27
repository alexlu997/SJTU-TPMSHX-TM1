"""Malformed native faces cannot become plausible scalar metrics after archival."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.tests.io_tm1.test_result_declarations import archived_native_result


def _result(dimension):
    result = archived_native_result(dimension)
    fields = {**result.fields, 'Tb': result.fields['Ta'] + 20.}
    metadata = {**result.field_metadata, 'Tb': dict(result.field_metadata['Ta'])}
    report = {side: {'direction': 0} for side in ('A', 'B')}
    pressure = {side: dict(P=np.array([[[100.], [20.]], [[100.], [20.]]]),
        dx=np.ones(2), dy=np.ones(2), dz=np.ones(1),
        inlet_frac=np.ones((2, 1)), outlet_frac=np.ones((2, 1)),
        outlet_geom_frac=np.ones(2)) for side in ('A', 'B')}
    if dimension == 2:
        for side in ('A', 'B'):
            fields['P_report_' + side] = np.array([[100., 100.], [20., 20.]])
            metadata['P_report_' + side] = {**metadata['Ta'], 'unit': 'Pa'}
    return replace(result, fields=fields, field_metadata=metadata, pressure_evidence=pressure,
        boundary_fluxes={**result.boundary_fluxes, 'report': report},
        metadata={**result.metadata, 'parameters': {'dir_A': 0, 'dir_B': 0,
            'boundary_openings': {side: {'in_geom_frac': np.ones(2), 'out_geom_frac': np.ones(2)}
                                  for side in ('A', 'B')}}})


def _sources(result, tmp_path):
    return result, load_result(save_result(result, tmp_path / 'result.h5'))


def _bad_faces(faces, defect):
    faces = list(faces)
    dimension = faces[0].ndim
    if defect == 'cell_centered':
        faces[0] = faces[0][:-1]
    elif defect == 'rank':
        faces[0] = faces[0][:, :, 0] if dimension == 3 else faces[0][:, :, None]
    elif defect == 'swap':
        faces[0], faces[1] = faces[1], faces[0]
    elif defect == 'empty':
        faces[0] = faces[0][:, :0]
    elif defect == 'other_axis':
        faces[-1] = faces[-1][..., :-1]
    elif defect == 'grid':
        shape = (3, 2, 1)[:dimension]
        faces = [np.ones(tuple(n + (i == axis) for i, n in enumerate(shape)))
                 for axis in range(dimension)]
    return tuple(faces)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['cell_centered', 'rank', 'swap', 'empty', 'other_axis', 'grid'])
def test_mass_and_outlet_share_topology_validation(tmp_path, dimension, defect):
    result = _result(dimension)
    expected = evaluate(result).metrics
    flux = {**result.boundary_fluxes,
            'mass_A': _bad_faces(result.boundary_fluxes['mass_A'], defect)}
    for source in _sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        for name in ('mass_flow_A', 'mass_imbalance_rel_A', 'T_out_A'):
            assert actual[name].status == 'invalid', (name, actual[name])
            assert actual[name].value is None
        for name in ('Q', 'Q_B', 'mass_flow_B', 'T_out_B', 'dP_A', 'dP_B'):
            assert actual[name] == expected[name]
            assert actual[name].status == 'available'


@pytest.mark.parametrize('dimension', [2, 3])
def test_zero_mass_preserves_zero_balance_but_not_outlet_temperature(tmp_path, dimension):
    result = _result(dimension)
    flux = {**result.boundary_fluxes,
            'mass_A': tuple(np.zeros_like(f) for f in result.boundary_fluxes['mass_A'])}
    for source in _sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        for name in ('mass_flow_A', 'mass_imbalance_rel_A'):
            assert (actual[name].status, actual[name].value) == ('available', 0.)
        assert actual['T_out_A'].status == 'invalid'
        assert actual['Q'].value == 10. and actual['mass_flow_B'].value == 2.


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('defect', ['cell_centered', 'rank', 'grid', 'enthalpy_shape', 'zero'])
def test_true_h_checks_its_own_mass_and_cell_evidence(tmp_path, dimension, defect):
    result = _result(dimension)
    mass = archived_native_result(3).boundary_fluxes['mass_A']
    h = np.arange(4.).reshape(2, 2, 1) + 100.
    native = dict(h_A=h, h_B=h + 100., h_in_A=110., h_in_B=190.,
                  mass_flux_A=mass, mass_flux_B=mass)
    if defect == 'enthalpy_shape':
        native['h_A'] = h[:, :, 0]  # Broadcasting used to manufacture a finite duty.
    elif defect == 'zero':
        native['mass_flux_A'] = tuple(np.zeros_like(f) for f in mass)
    else:
        native['mass_flux_A'] = _bad_faces(mass, defect)
    result = replace(result, boundary_fluxes={**result.boundary_fluxes, 'true_h': native},
                     metadata={**result.metadata, 'thermal_mode': 'true_h'})
    for source in _sources(result, tmp_path):
        actual = evaluate(source).metrics
        for name in ('Q', 'Q_A', 'energy_imbalance_rel'):
            assert actual[name].status == ('available' if defect == 'zero' else 'invalid')
        if defect == 'zero':
            assert actual['Q'].value == 0.
        assert actual['Q_B'].value == -25.
        assert actual['mass_flow_A'].value == actual['mass_flow_B'].value == 2.
        assert actual['T_out_A'].value == 302.5


@pytest.mark.parametrize('defect', ['cell_centered', 'rank', 'grid'])
@pytest.mark.parametrize('fine', [False, True])
def test_two_d_model_h_uses_the_same_staggered_contract(tmp_path, defect, fine):
    result = _result(2)
    flux = mutable_data(result.boundary_fluxes)
    balance = flux['fine']['model_h_balance'] if fine else flux['model_h']
    balance['A']['h_faces_W_per_m'] = _bad_faces(balance['A']['h_faces_W_per_m'], defect)
    if fine:
        flux['fine'].update(dx=result.grid['dx'], dy=result.grid['dy'])
    for source in _sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        assert actual['Q_richardson_A'].status == 'invalid'
        assert actual['Q'].status == ('available' if fine else 'invalid')
        assert actual['Q_B'].value == -10.
        assert actual['mass_flow_A'].value == 2.


@pytest.mark.parametrize('defect', ['empty', 'missing_face', 'extra', 'rank', 'empty_face',
                                   'pair_shape', 'grid', 'missing_side', 'missing_ledger', 'zero'])
def test_three_d_model_h_requires_six_consistent_planes(tmp_path, defect):
    result = _result(3)
    flux = mutable_data(result.boundary_fluxes)
    faces = flux['model_h']['A']
    if defect == 'empty':
        faces.clear()
    elif defect == 'missing_face':
        del faces['x-']
    elif defect == 'extra':
        faces['other'] = np.zeros((2, 1))
    elif defect == 'rank':
        faces['x-'] = faces['x-'].ravel()
    elif defect == 'empty_face':
        faces['x-'] = np.zeros((0, 1))
    elif defect == 'pair_shape':
        faces['x+'] = np.zeros((3, 1))
    elif defect == 'grid':
        for name in ('y-', 'y+'):
            faces[name] = np.zeros((3, 1))
        for name in ('z-', 'z+'):
            faces[name] = np.zeros((3, 2))
    elif defect == 'missing_side':
        del flux['model_h']['A']
    elif defect == 'missing_ledger':
        del flux['model_h']
    elif defect == 'zero':
        for key in faces:
            faces[key] = np.zeros_like(faces[key])
    for source in _sources(replace(result, boundary_fluxes=flux), tmp_path):
        actual = evaluate(source).metrics
        status = ('insufficient_data' if defect.startswith('missing_') and defect != 'missing_face'
                  else 'available' if defect == 'zero' else 'invalid')
        for name in ('Q', 'Q_A', 'energy_imbalance_rel'):
            assert actual[name].status == status, (name, actual[name])
        if defect == 'zero':
            assert actual['Q'].value == 0.
        if defect != 'missing_ledger':
            assert actual['Q_B'].value == -10.
        assert actual['mass_flow_A'].value == 2.
        assert actual['T_out_A'].value == 302.5
        assert actual['dP_A'].status == 'available'


@pytest.mark.parametrize('thermal_mode', ['model_h', 'true_h'])
def test_two_d_portable_sequence_faces_keep_existing_support(tmp_path, thermal_mode):
    result = _result(2)
    flux = mutable_data(result.boundary_fluxes)
    for side in ('A', 'B'):
        flux['mass_' + side] = [face.tolist() for face in flux['mass_' + side]]
    if thermal_mode == 'true_h':
        h = np.arange(4.).reshape(2, 2, 1) + 100.
        mass = archived_native_result(3).boundary_fluxes['mass_A']
        flux['true_h'] = {key: value for side in ('A', 'B') for key, value in (
            ('h_' + side, h), ('h_in_' + side, 110.),
            ('mass_flux_' + side, [face.tolist() for face in mass]))}
    result = replace(result, boundary_fluxes=flux,
                     metadata={**result.metadata, 'thermal_mode': thermal_mode})
    for source in _sources(result, tmp_path):
        metrics = evaluate(source).metrics
        assert metrics['T_out_A'].value == 302.5
        assert metrics['Q'].value == (15. if thermal_mode == 'true_h' else 10.)
