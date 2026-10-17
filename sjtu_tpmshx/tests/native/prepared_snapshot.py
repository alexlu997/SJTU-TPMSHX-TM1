"""Read native fields at a complete boundary for preparation checks."""
from importlib import import_module

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.module_ports import resolve_control


def native_prepared_state(case, *, phase=None):
    dimension = case.grid['dimension']
    preparation = import_module(f'sjtu_tpmshx.solvers.backends.prepared_{dimension}d')
    execution = import_module(f'sjtu_tpmshx.solvers.backends.cpp.full_{dimension}d')
    cfg, prepared = preparation.build_execution_inputs(case)
    control = resolve_control(RunControl())
    driver = getattr(execution, f'NativeFull{dimension}DDriver')(
        control.native_library, table_directory=control.native_table_directory)
    captured = {}
    target = phase if phase is not None else (7 if dimension == 2 else 8)

    class StateBoundary(Exception):
        pass

    def capture(state):
        if int(state['state.phase'][0]) == target:
            captured.update(state)
            raise StateBoundary

    try:
        driver.run_prepared(cfg, prepared, control, checkpoint=capture)
    except StateBoundary:
        return cfg, prepared, captured
    raise AssertionError(f'native run did not reach phase {target}')
