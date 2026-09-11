"""Observe original-budget 2D screening without changing solver inputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from sjtu_tpmshx.optimization import evaluator as app
from sjtu_tpmshx.solvers.continuous_field import uniform_field
from sjtu_tpmshx.tests import test_evaluator_frozen_values as pins


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('uniform', 'nonuniform'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert Path(app.__file__).resolve().is_relative_to(Path.cwd().resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    git_env = {k: v for k, v in os.environ.items()
               if k not in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE')}
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], env=git_env, text=True).strip()
    arrays, scalars = {}, {}

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

    thermal_code = app.solve_full_domain.__code__
    evaluator_code = app.evaluate_design.__code__

    def observe(frame, event, result):
        if frame.f_code is thermal_code and event in ('call', 'return'):
            save('thermal/' + event, dict(frame.f_locals))
            if event == 'call':
                for side in ('sA', 'sB'):
                    save('flow/' + side, vars(frame.f_back.f_locals[side]))
        elif frame.f_code is evaluator_code and event == 'return':
            save('evaluator/return', dict(frame.f_locals))
            save('outputs', result)

    save('source_sha', sha)
    save('source_file', app.__file__)
    save('interpreter', sys.executable)
    fc = (uniform_field(6., .4, 'Diamond', 17., L_domain=.1, H_domain=.05)
          if args.case == 'uniform' else None)
    x = None if fc is not None else pins._X_NONUNIF.copy()
    sys.setprofile(observe)
    try:
        values = app.evaluate_design(x, dict(pins._FAST_CFG), fc=fc)
    finally:
        sys.setprofile(None)
        np.savez(args.output / 'native.npz', **arrays)
        (args.output / 'capture.json').write_text(json.dumps(scalars, indent=2) + '\n')
    for key in ('thermal/return/Ta', 'flow/sA/P', 'flow/sB/P',
                'evaluator/return/arrays/L_field'):
        assert key in arrays, f'missing native evidence: {key}'
    summary = dict(source_sha=sha, case=args.case, outputs=list(values),
                   units=['W/m', 'Pa', 'kg/m'], physical_validation='unestablished')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
