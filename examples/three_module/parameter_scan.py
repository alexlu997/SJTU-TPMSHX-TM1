"""Run two screening parameter cases using only public module/file APIs."""
import argparse
import json
from pathlib import Path
import numpy as np

from sjtu_tpmshx.preprocess.api import prepare_screening_2d
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.case_io import save_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.metrics_io import save_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    reports = []
    for velocity in (1., 2.):
        name = f'u-{velocity:g}'
        folder = args.output / name
        folder.mkdir(parents=True, exist_ok=True)
        case = prepare_screening_2d(
            np.r_[np.full(8, 6.), np.full(8, .4)],
            dict(Nx=8, Ny=6, u_A=velocity, u_B=1., max_iter_simple=800,
                 max_iter_energy=1500, n_rho_loops=1), case_id=name)
        result = run_case(case)
        metrics = evaluate(result)
        save_case(case, folder / 'case.yaml')
        save_result(result, folder / 'results.h5')
        save_metrics(metrics, folder / 'metrics.json')
        reports.append(dict(case_id=name, Q=metrics.metrics['Q'].value,
                            Q_unit=metrics.metrics['Q'].spec.unit,
                            converged=result.run_status['converged'],
                            physical_validation=result.run_status['physical_validation']))
    (args.output / 'summary.json').write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports))


if __name__ == '__main__':
    main()
