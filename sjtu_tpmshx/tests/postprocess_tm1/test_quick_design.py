"""Quick-design reduction also runs in the minimal postprocess install."""
from dataclasses import replace

import numpy as np

from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.postprocess.api import evaluate


def test_quick_native_duty_pressure_and_unconverged_state():
    result = FieldResult(
        result_id='quick', case_id='point', backend_id='python', backend_version='quick_design_v1',
        fields={'Ta': np.full((2, 2, 1), 400.), 'Tb': np.full((2, 2, 1), 350.)},
        boundary_fluxes={side: dict(mass_flow_kg_s=.1, cp_J_kgK=1000., inlet_temperature_K=t)
                         for side, t in (('A', 500.), ('B', 300.))},
        pressure_evidence={side: dict(inlet_absolute_Pa=200000., outlet_absolute_Pa=199000.)
                           for side in ('A', 'B')},
        run_status={'execution': 'completed', 'converged': False},
        metadata=dict(mode='quick_design', dimension=3, model='plug_ltne_analytic_dp_v1',
                      parameters={'arrangement': 'cross'}, reporting_reference={'Q': 999999.}))
    metrics = evaluate(result).metrics
    assert metrics['Q'].value == 10000. and metrics['Q'].spec.unit == 'W'
    assert metrics['Q_cold'].value == 5000.
    assert metrics['dP_A'].value == 1000.
    assert metrics['mass'].status == 'unsupported'
    assert result.run_status['converged'] is False
    changed = replace(result, fields={**result.fields, 'Ta': np.full((2, 2, 1), 450.)})
    assert evaluate(changed).metrics['Q'].value == 5000.
