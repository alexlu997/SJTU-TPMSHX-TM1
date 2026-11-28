"""Run the saved production stage and keep its raw native capture for audits.

The wrapper records the arguments of ``capture_result`` and returns its public
``FieldResult`` unchanged. Tests can then compare raw native evidence with the
published result of the same run. A 3D run also copies the raw native arrays
that the application capture does not detach.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tm1.cpp_interface import full_2d_stage, full_3d_stage
from tm1.solvers import full_2d, full_3d
from tm1.run_control.module_ports import RunControl
from tests.python.native.shared_library import library_path

ROOT = Path(__file__).resolve().parents[3]
TABLES = ROOT / '.cache/native-deps/tables'


def stage_control(**options):
    """Return a C++ run control for the configured solver library and table cache."""
    options.setdefault('native_table_directory', str(TABLES))
    return RunControl(backend='cpp', native_library=str(library_path()), **options)


def stage_module(case):
    return full_2d if case.grid['dimension'] == 2 else full_3d


def native_3d_arrays(result, shape):
    """Copy the raw 3D thermal and real-axis flow arrays of one native result."""
    copy = full_3d_stage._copy
    arrays = {name: tuple(copy(value, shape) for value in getattr(result, name))
              for name in ('temperature', 'thermal_pressure', 'hv', 'conductivity')}
    arrays['flow'] = [None if not flow.widths[0].size else dict(
        pressure_real=copy(flow.pressure_real, shape), density_real=copy(flow.density_real, shape),
        velocity_real=tuple(copy(value, shape) for value in flow.velocity_real)) for flow in result.flow]
    return arrays


def run_stage(case, control=None, *, resume_state=None, checkpoint=None, checkpoint_due=None):
    """Run ``case`` through ``run_case`` and return the result with its raw capture.

    The returned namespace has ``result``, ``native``, ``cfg`` and ``prepared``.
    A 3D namespace also has ``arrays`` from ``native_3d_arrays``.
    """
    module = stage_module(case)
    original = module.capture_result
    captured, arrays = [], []

    def capture(case, cfg, prepared, native, *args, **kwargs):
        captured.append(dict(cfg=cfg, prepared=prepared, native=native))
        return original(case, cfg, prepared, native, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(module, 'capture_result', capture)
        if module is full_3d:
            detach = full_3d_stage._detach

            def copied(result, shape, *args, **kwargs):
                arrays.append(native_3d_arrays(result, shape))
                return detach(result, shape, *args, **kwargs)
            patcher.setattr(full_3d_stage, '_detach', copied)
        result = module.run_case(case, stage_control() if control is None else control,
                                 resume_state=resume_state, checkpoint=checkpoint,
                                 checkpoint_due=checkpoint_due)
    record, = captured
    if arrays:
        record['arrays'], = arrays
    return SimpleNamespace(result=result, **record)


def saved_2d_inputs(case):
    """Return the settings that the saved 2D stage validates before it packs ``case``."""
    driver = full_2d_stage.StageDriver(library_path())
    entries = full_2d_stage.stage_entries(driver.library)
    cfg, prepared, _ = full_2d.saved_inputs(
        case, full_2d.execution_grid(case),
        check_experiment=lambda spec: full_2d_stage.check_experiment(entries, spec, full_2d._ERROR_TYPES),
        port_windows_fit=entries['port_windows_fit'])
    return cfg, prepared, full_2d._run_settings(cfg)


class _Paused(Exception):
    pass


def first_state(case, control=None):
    """Return the first saved-stage snapshot of ``case`` and stop before the complete solve."""
    states = []

    def pause(state):
        states.append(state)
        raise _Paused

    with pytest.raises(_Paused):
        stage_module(case).run_case(case, stage_control() if control is None else control, checkpoint=pause)
    return states[0]
