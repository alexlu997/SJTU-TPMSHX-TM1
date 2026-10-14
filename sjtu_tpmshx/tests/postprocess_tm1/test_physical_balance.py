"""Signed physical evidence stays distinct from acceptance and display fields."""
from dataclasses import replace
import json
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.postprocess.api import evaluate_physical_balance


FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')


def sample_result(dimension):
    shape = (2,) * dimension
    shape3 = shape + ((1,) if dimension == 2 else ())
    grid = dict(dimension=dimension, length_unit='m', axis_order=tuple('xyz'[:dimension]))
    for axis in 'xyz'[:dimension]:
        grid['d' + axis] = np.array([.1, .2])
        grid[axis + '_edges'] = np.array([0., .1, .1 + .2])
    def planes():
        return {name: np.zeros(tuple(n for d, n in enumerate(shape3) if d != i // 2))
                for i, name in enumerate(FACES)}
    adv = {side: planes() for side in ('A', 'B', 'solid')}
    diff = {side: planes() for side in ('A', 'B', 'solid')}
    adv['A']['x+'].flat[0] = 4.
    adv['B']['x-'].flat[0] = -5.
    diff['A']['x-'].flat[0] = 2.
    residuals = {side: np.zeros(shape) for side in ('A', 'B', 'solid')}
    residuals['A'].flat[:2] = [3., -2.]
    residuals['B'].flat[0] = -1.
    ledger = dict(definition='physical_heat_ledger_v1', physical_dimension=dimension,
        power_units='W/m' if dimension == 2 else 'W', physical_boundary_complete=True,
        solved=dict.fromkeys(('A', 'B', 'solid'), True), residual=residuals,
        advective_out=adv, diffusive_out=diff,
        source_integral=dict(A=1., B=0., solid=0.), prescribed_b_power=0.)
    mass = [np.zeros(tuple(n + (d == axis) for d, n in enumerate(shape)))
            for axis in range(dimension)]
    mass[0][(slice(None),) + (0,) * (dimension - 1)] = [2., 2.5, 3.]
    return FieldResult('physical', 'case', 'fixture', grid=grid,
        boundary_fluxes=dict(energy=ledger, mass_A=mass, mass_B=None,
                             state='last thermal input', fine=None),
        run_status=dict(execution='completed', converged=False, outer_index=7),
        metadata=dict(dimension=dimension, quantity_basis='per_unit_depth' if dimension == 2 else 'total'))


@pytest.mark.parametrize('dimension', [2, 3])
def test_signed_balances_do_not_cancel_cell_residuals(dimension):
    result = sample_result(dimension)
    summary = evaluate_physical_balance(result)
    assert summary['state'] == 'last thermal input' and summary['outer_index'] == 7
    assert 'passed' not in summary
    mass = summary['mass']['A']
    assert (mass['inflow'], mass['outflow'], mass['residual']['signed_sum']) == (2., 3., 1.)
    assert mass['relative_net'] == pytest.approx(1/3)
    assert mass['residual']['l1'] == 1. and mass['telescoping_error'] == 0.
    assert summary['mass']['B']['status'] == 'unavailable'
    energy = summary['energy']
    assert energy['units'] == ('W/m' if dimension == 2 else 'W')
    assert energy['residual_sum'] == energy['net_external_in'] == energy['telescoping_error'] == 0.
    assert energy['boundary_out'] == energy['source_integral'] == 1.
    assert energy['scale'] == 6.
    assert energy['phases']['A']['residual']['l1'] == 5.
    assert energy['phases']['A']['residual']['cell_max_relative'] == 3. * 2**dimension / 6.
    altered = replace(result, metadata={**result.metadata, 'reporting_reference': dict(Q=1e99)},
                      fields=dict(Ta_display=np.full((2,) * dimension, -1e99)))
    assert evaluate_physical_balance(altered) == summary


@pytest.mark.parametrize('dimension', [2, 3])
def test_new_process_reads_balances_without_solver_or_eos(tmp_path, dimension):
    result = sample_result(dimension)
    path = tmp_path / 'physical.h5'
    save_result(result, path)
    child = subprocess.run([sys.executable, '-c', r"""
import json, sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate_physical_balance
print(json.dumps(evaluate_physical_balance(load_result(sys.argv[1])), allow_nan=False))
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'numba', 'CoolProp', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
""", str(path)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == evaluate_physical_balance(result)


def test_missing_or_incomplete_boundary_evidence_is_not_zero():
    result = sample_result(2)
    summary = evaluate_physical_balance(replace(result, boundary_fluxes={}))
    assert summary['energy']['status'] == 'unavailable'
    assert 'residual_sum' not in summary['energy']
    flux = mutable_data(result.boundary_fluxes)
    flux['energy']['physical_boundary_complete'] = False
    summary = evaluate_physical_balance(replace(result, boundary_fluxes=flux))
    assert summary['energy']['physical_boundary_complete'] is False
    flux['energy']['physical_boundary_complete'] = None
    assert evaluate_physical_balance(replace(result, boundary_fluxes=flux))['energy']['physical_boundary_complete'] is None


@pytest.mark.parametrize('damage, message', [
    ('dimension', 'units or dimension'), ('units', 'units or dimension'),
    ('residual', 'residual shape'), ('face', 'boundary'), ('nan', 'finite'),
    ('source', 'scalar source'), ('unsolved', 'unsolved phase'),
])
def test_reject_contradictory_physical_evidence(damage, message):
    result = sample_result(2)
    flux = mutable_data(result.boundary_fluxes)
    ledger = flux['energy']
    if damage == 'dimension': ledger['physical_dimension'] = 3
    elif damage == 'units': ledger['power_units'] = 'W'
    elif damage == 'residual': ledger['residual']['A'] = np.zeros((2, 2, 1))
    elif damage == 'face': ledger['advective_out']['A']['x+'] = np.zeros((2, 2))
    elif damage == 'nan': ledger['residual']['A'][0, 0] = np.nan
    elif damage == 'source': ledger['source_integral']['A'] = [1.]
    else: ledger['solved']['B'] = False
    with pytest.raises(ValueError, match=message):
        evaluate_physical_balance(replace(result, boundary_fluxes=flux))


def test_prescribed_reservoir_is_separate_from_a_solved_b_equation():
    result = sample_result(3)
    flux = mutable_data(result.boundary_fluxes)
    ledger = flux['energy']
    ledger['solved']['B'] = False
    for key in ('residual', 'advective_out', 'diffusive_out', 'source_integral'):
        ledger[key]['B'] = None
    ledger['prescribed_b_power'] = 6.
    summary = evaluate_physical_balance(replace(result, boundary_fluxes=flux))['energy']
    assert summary['phases']['B']['status'] == 'not_solved'
    assert summary['prescribed_b_power'] == 6.
    assert summary['net_external_in'] == summary['residual_sum'] == 1.
    assert summary['telescoping_error'] == 0.
