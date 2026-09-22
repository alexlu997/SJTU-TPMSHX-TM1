"""The current Shanghai preparation→thermal path passes full porosity once."""
import inspect

import numpy as np
import pandas as pd
import pytest


def test_validate_shanghai_passes_full_epsilon(monkeypatch):
    from sjtu_tpmshx.validation.cases.validate_shanghai_3d_real import _pipeline_config
    from sjtu_tpmshx.validation.harness._case_sets import shanghai_spec
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime

    row = {i: 0. for i in range(34)}
    row.update({5: .0023, 7: .0108, 24: 20., 28: 120., 30: 1500.})
    df = pd.DataFrame([row])
    df['water_P_in_abs_Pa'] = 101500.
    case = prepare_case(_pipeline_config(0, df, 4, 4, 2, max_outer=2),
                        case_id='shanghai-full-porosity')
    signature = inspect.signature(runtime.solve_full_domain_3d)
    captured = {}

    class Captured(Exception):
        pass

    def observe_thermal(*args, **kwargs):
        captured['epsilon'] = signature.bind(*args, **kwargs).arguments['epsilon']
        raise Captured

    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', lambda *a, **k: (False, 0))
    monkeypatch.setattr(runtime, 'solve_full_domain_3d', observe_thermal)
    with pytest.raises(Captured):
        run_case(case)
    np.testing.assert_array_equal(captured['epsilon'], case.design_fields['eps_arr'])
    # The thermal kernel applies the phase split; pre-halving here would
    # make symmetric fluid fractions epsilon_full/4 rather than epsilon_full/2.
    np.testing.assert_allclose(captured['epsilon'], shanghai_spec().eps, rtol=1e-12)
