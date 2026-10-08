"""Native input borrowing preserves the writable Python execution contract."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d import execution as execution_2d
from sjtu_tpmshx.solvers.backends.python.three_d import execution as execution_3d
from sjtu_tpmshx.tests.solver_tm1.test_prepared_continuous_field import _config


@pytest.mark.parametrize('dimension', [2, 3])
def test_native_design_is_readonly_while_public_builder_detaches(dimension):
    config = _config(volume=dimension == 3)
    config.solver = replace(config.solver, Nx=12, Nz=1 if dimension == 2 else 3)
    case = prepare_case(config, case_id='design-ownership')
    execution = execution_2d if dimension == 2 else execution_3d
    copied = execution.build_execution_inputs(case)
    borrowed = execution._build_execution_inputs(case, copy_design=False)
    copies = copied[0]['za'] if dimension == 2 else copied[1]['design']
    views = borrowed[0]['za'] if dimension == 2 else borrowed[1]['design']
    for key, source in case.design_fields.items():
        if not isinstance(source, np.ndarray):
            continue
        converted = dimension == 2 and key in ('L_field_m', 't_field_m')
        target = key[:-2] if converted else key
        np.testing.assert_array_equal(views[target], copies[target])
        assert not np.shares_memory(copies[target], source)
        assert copies[target].flags.writeable
        if converted:
            assert not np.shares_memory(views[target], source)
        else:
            assert views[target] is source
            with pytest.raises(ValueError):
                views[target].setflags(write=True)
        saved = source.copy()
        copies[target].flat[0] = 0.
        np.testing.assert_array_equal(source, saved)
    # Only design arrays are borrowed; runtime parameters remain independent.
    key = 'thermal_geometry'
    field = borrowed[0][key]['fields']['D_h']
    assert field.flags.writeable
    assert not np.shares_memory(field, case.parameters[key]['fields']['D_h'])


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('copy_design', [False, True])
def test_borrowing_keeps_prepared_input_validation(dimension, copy_design):
    config = _config(volume=dimension == 3)
    config.solver = replace(config.solver, Nx=12, Nz=1 if dimension == 2 else 3)
    case = prepare_case(config, case_id='invalid-borrow')
    execution = execution_2d if dimension == 2 else execution_3d
    key = 'K_ss_arr' if dimension == 2 else 'K_ss'
    invalid = replace(case, design_fields={**case.design_fields, key: np.ones((2, 3))})
    with pytest.raises(ValueError, match='does not match'):
        execution._build_execution_inputs(invalid, copy_design=copy_design)
    refs = (ModelRef('fluid', 'unknown'), *case.model_refs[1:])
    with pytest.raises(ValueError, match='unknown model'):
        execution._build_execution_inputs(replace(case, model_refs=refs), copy_design=copy_design)
