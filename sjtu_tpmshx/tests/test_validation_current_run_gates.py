"""Current-run verdicts, with synthetic results instead of expensive sweeps."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.validation.cases import validate_sco2_v1 as v1


@pytest.mark.parametrize('damage', [None, 'Q_W', 'dP_A_Pa', 'dP_B_Pa',
                                   'rmsre', 'bias', 'fixed_dp', 'Q_A',
                                   'mass_imbalance_rel_A', 'mass_imbalance_rel_B',
                                   'enthalpy_imbalance_rel'])
@pytest.mark.parametrize('invalid', [np.nan, np.inf])
def test_v1_rejects_nonfinite_gated_metrics(monkeypatch, damage, invalid):
    point = SimpleNamespace(dp_core_Pa=100., Um_m_s=.8, Tref=350., Re=10080.)
    metrics = {topo: dict(rmsre=.01, bias=0., limit=limit)
               for topo, limit in [('Diamond', .2), ('Gyroid', .15)]}
    result = SimpleNamespace(Q_W=100., dP_A_Pa=100., dP_B_Pa=100., converged=True,
                             residuals=dict(Q_A=100., mass_imbalance_rel_A=0.,
                                            mass_imbalance_rel_B=0., enthalpy_imbalance_rel=0.))
    result_3d = deepcopy(result)
    result_3d.Q_W *= .021
    if damage in ('Q_W', 'dP_A_Pa', 'dP_B_Pa'):
        setattr(result, damage, invalid)
    elif damage in ('rmsre', 'bias'):
        metrics['Gyroid'][damage] = invalid
    elif damage in result.residuals:
        result.residuals[damage] = invalid
    monkeypatch.setattr(v1, '_cfd_check', lambda: (metrics, point))
    monkeypatch.setattr(v1, 'FullCore3CellFixedDFV2', lambda *a: None)
    monkeypatch.setattr(v1, '_fixed_dp', lambda *a: invalid if damage == 'fixed_dp' else 100.)
    monkeypatch.setattr(v1, 'compute_result', lambda cfg: result_3d if cfg.is_3d else result)
    assert v1.main() == (0 if damage is None else 1)
