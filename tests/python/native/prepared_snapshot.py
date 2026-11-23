"""Read native fields at a complete saved-stage boundary for preparation checks."""
from sjtu_tpmshx.cpp_interface import full_2d_stage, full_3d_stage
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.run_control.module_ports import resolve_control


def native_prepared_state(case, *, phase=None):
    """Return the native snapshot at the first ``phase`` boundary of ``case``."""
    dimension = case.grid['dimension']
    stage = full_2d_stage if dimension == 2 else full_3d_stage
    control = resolve_control(RunControl())
    captured = {}
    target = phase if phase is not None else (7 if dimension == 2 else 8)

    class StateBoundary(Exception):
        pass

    def capture(state):
        if int(state['state.phase'][0]) == target:
            captured.update(state)
            raise StateBoundary

    try:
        stage.run_case(case, control, checkpoint=capture)
    except StateBoundary:
        return captured
    raise AssertionError(f'native run did not reach phase {target}')
