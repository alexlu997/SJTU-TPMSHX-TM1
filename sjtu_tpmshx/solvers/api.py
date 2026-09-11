"""Public prepared-case execution entry point."""
from dataclasses import replace
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.domain.run_warnings import warning_scope, warning_messages
from sjtu_tpmshx.domain.provenance import source_context


def run_case(case, control=RunControl()):
    if control.backend != 'python':
        raise ValueError(f'unsupported backend: {control.backend}')
    dimension = case.grid.get('dimension')
    mode = case.metadata.get('mode', 'full')
    if mode == 'quick_design':
        from .backends.python.quick_design.execution import run_case as run
    elif mode == 'screening_2d':
        from .backends.python.screening.two_d import run_case as run
    elif mode == 'screening_3d':
        from .backends.python.screening.three_d import run_case as run
    elif mode != 'full':
        raise ValueError(f'unsupported solver mode: {mode}')
    elif dimension == 2:
        from .backends.python.two_d.execution import run_case as run
    elif dimension == 3:
        from .backends.python.three_d.execution import run_case as run
    else:
        raise ValueError(f'unsupported physical dimension: {dimension}')
    provenance = dict(preparation=case.metadata.get('provenance', {'status':'not_recorded'}),
                      execution=source_context())
    with warning_scope({}) as records:
        result = run(case, control)
    diagnostics = dict(result.metadata.get('diagnostics', {}))
    diagnostics['warnings_list'] = tuple(dict.fromkeys((
        *case.metadata.get('warnings', ()), *diagnostics.get('warnings_list', ()),
        *warning_messages(records))))
    return replace(result, metadata={**result.metadata, 'diagnostics': diagnostics,
                                     'provenance': provenance})
