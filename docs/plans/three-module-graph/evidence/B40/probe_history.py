"""Capture unmodified historical 3D screening calls; run from the source checkout.

Use the checkout's .venv-path interpreter with runpy.run_path, so imports
resolve from that checkout. Output is diagnostic evidence, not public Result IO.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from sjtu_tpmshx.optimization import evaluator_3d as app
from sjtu_tpmshx.tests import test_evaluator_frozen_values as pins


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('3d-uniform', '3d-nonuniform'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-outer', type=int)
    parser.add_argument('--simple-iterations', type=int)
    parser.add_argument('--energy-iterations', type=int)
    parser.add_argument('--convergence-mode', choices=('legacy', 'f2'))
    parser.add_argument('--q-rel-tol', type=float)
    parser.add_argument('--prepared-backend', action='store_true')
    args = parser.parse_args()
    if args.prepared_backend:
        from sjtu_tpmshx.solvers.backends.python.screening import three_d as core
    else:
        from sjtu_tpmshx.core import evaluators as core
    assert Path(core.__file__).resolve().is_relative_to(Path.cwd().resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    git_env = {k: v for k, v in os.environ.items()
               if k not in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE')}
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], env=git_env, text=True).strip()
    cfg = {**app.DEFAULT_CONFIG_3D, **pins._CFG_3D}
    for value, key in ((args.max_outer, 'max_outer_3d'),
                       (args.simple_iterations, 'max_iter_simple'),
                       (args.energy_iterations, 'max_iter_energy')):
        if value is not None:
            cfg[key] = value
    x = (np.r_[np.full(8, 4.), np.full(8, .6)] if args.case == '3d-uniform'
         else pins._X_NONUNIF.copy())
    arrays = {}
    scalars = {}

    def save(prefix, value):
        if isinstance(value, np.ndarray):
            arrays[prefix] = value.copy()
        elif isinstance(value, np.generic):
            scalars[prefix] = value.item()
        elif value is None or isinstance(value, (str, int, float, bool)):
            scalars[prefix] = value
        elif isinstance(value, dict):
            for key, item in value.items():
                save(prefix + '/' + str(key), item)
        elif isinstance(value, (tuple, list)):
            for i, item in enumerate(value):
                save(prefix + '/' + str(i), item)

    original_thermal = core.solve_full_domain_3d
    thermal_code = original_thermal.__code__
    core_code = (core.run_case if args.prepared_backend else core.evaluate_3d).__code__
    thermal_call = 0

    def capture(frame, event, result):
        nonlocal thermal_call
        if frame.f_code is thermal_code and event in ('call', 'return'):
            if event == 'call':
                thermal_call += 1
                caller = frame.f_back
                if caller.f_code is not core_code:
                    caller = caller.f_back  # explicit q-rel-tol experiment wrapper
                for side in ('sA', 'sB'):
                    save(f'thermal_{thermal_call}/flow/{side}', vars(caller.f_locals[side]))
            save(f'thermal_{thermal_call}/{event}', dict(frame.f_locals))
            if event == 'return':
                save(f'thermal_{thermal_call}/output', result)
        elif frame.f_code is core_code and event == 'return':
            save('core/locals', dict(frame.f_locals))
            save('core/result', dict(result.run_status) if args.prepared_backend else result)
            for side in ('sA', 'sB'):
                if side in frame.f_locals:
                    save('core/' + side, vars(frame.f_locals[side]))

    original = app._evaluate_3d_dict

    def evaluate(*pos, **kw):
        if args.convergence_mode is not None:
            kw['convergence_mode'] = args.convergence_mode
        return original(*pos, **kw)

    app._evaluate_3d_dict = evaluate
    if args.q_rel_tol is not None:
        def thermal(*pos, **kw):
            kw['q_rel_tol'] = args.q_rel_tol
            return original_thermal(*pos, **kw)
        core.solve_full_domain_3d = thermal
    save('input/config', cfg)
    save('input/x_mm', x)
    save('source_sha', sha)
    save('source_file', core.__file__)
    save('interpreter', sys.executable)
    save('environment', {k: v for k, v in os.environ.items()
                         if k.startswith(('TPMSHX_', 'NUMBA_', 'OMP_', 'MKL_', 'OPENBLAS_'))})
    save('requested_convergence_mode', args.convergence_mode)
    save('requested_q_rel_tol', args.q_rel_tol)
    sys.setprofile(capture)
    try:
        values = app.evaluate_design_3d(x, cfg)
    finally:
        sys.setprofile(None)
        app._evaluate_3d_dict = original
        core.solve_full_domain_3d = original_thermal
        np.savez(args.output / 'native.npz', **arrays)
        (args.output / 'capture.json').write_text(
            json.dumps(scalars, indent=2, allow_nan=True) + '\n', encoding='utf-8')
    summary = dict(source_sha=sha, case=args.case, outputs=list(values),
                   units=['W/m', 'Pa', 'kg/m'], thermal_calls=thermal_call,
                   converged=scalars.get('core/result/converged'),
                   physical_validation='unestablished',
                   boundary_energy_status='raw_evidence_captured_not_yet_reduced')
    for key in ('thermal_1/call/ufA', 'thermal_1/return/ufA',
                'thermal_1/return/Ta', 'core/locals/arrays/h_vB_arr'):
        assert key in arrays, f'missing native capture: {key}'
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
