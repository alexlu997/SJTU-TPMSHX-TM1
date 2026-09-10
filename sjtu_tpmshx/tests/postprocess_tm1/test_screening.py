"""Offline screening uses native inputs and keeps unsupported/rejected metrics."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.api import evaluate


@pytest.mark.parametrize('dimension,q', [(2, 16.), (3, 4.8)])
def test_native_screening_reductions(dimension, q):
    shape = (2,) * dimension
    pressure = np.full(shape, 10.)
    pressure[:, 0] = 20.
    face_shape = (2,) if dimension == 2 else (2, 2)
    evidence = dict(P_gauge_Pa=pressure, inlet_fraction=np.ones(face_shape),
                    outlet_fraction=np.ones(face_shape), dx_m=np.full(2, .1), dz_m=np.full(2, .15))
    result = FieldResult('native', 'case', 'fixture',
        grid=dict(dimension=dimension, dx=np.full(2, .1), dy=np.full(2, .2), dz=np.full(2, .15)),
        fields=dict(Tb=np.full(shape, 300.), Ts=np.full(shape, 320.),
                    h_vB_arr=np.full(shape, 10.), eps_arr=np.full(shape, .5)),
        pressure_evidence=dict(A=evidence, B=evidence),
        run_status=dict(execution='completed', converged=False),
        metadata=dict(dimension=dimension, mode=f'screening_{dimension}d',
                      solid_density_kg_m3=2700., cached_Q=99999.))
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == pytest.approx(q)
    assert metrics['dP_A'].value == 10.
    assert metrics['mass'].value == pytest.approx(108. if dimension == 2 else 32.4)
    assert metrics['T_out_A'].status == 'unsupported'
    changed = replace(result, fields={**result.fields, 'Ts': np.full(shape, 310.)})
    assert evaluate(changed).metrics['Q'].value == pytest.approx(q / 2.)
    rejected = replace(result, run_status=dict(execution='rejected', converged=False, reason='choked'))
    assert evaluate(rejected).metrics['Q'].status == 'invalid'
    assert evaluate(rejected).metrics['mass'].value == metrics['mass'].value
