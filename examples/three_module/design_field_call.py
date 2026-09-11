"""Change a prepared effective-conductivity field; no private solver mutation.

This is a forward screening example. Gradients/adjoints are not implemented.
"""
import argparse
from dataclasses import replace
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
    base = prepare_screening_2d(
        np.r_[np.full(8, 6.), np.full(8, .4)],
        dict(Nx=8, Ny=6, u_A=1., u_B=1., max_iter_simple=800,
             max_iter_energy=1500, n_rho_loops=1), case_id='uniform-effective-field')
    conductivity = np.asarray(base.design_fields['K_ss_arr']) * np.linspace(.5, 1., 8)[:, None]
    changed = replace(base, case_id='graded-effective-field',
                      design_fields={**base.design_fields, 'K_ss_arr': conductivity},
                      metadata={**base.metadata, 'field_update': 'supplied effective solid conductivity, W/(m K)'})
    reports = []
    for case in (base, changed):
        folder = args.output / case.case_id
        folder.mkdir(parents=True, exist_ok=True)
        result = run_case(case)
        metrics = evaluate(result)
        save_case(case, folder / 'case.yaml')
        save_result(result, folder / 'results.h5')
        save_metrics(metrics, folder / 'metrics.json')
        reports.append(dict(case_id=case.case_id, Q=metrics.metrics['Q'].value,
                            Q_unit=metrics.metrics['Q'].spec.unit,
                            converged=result.run_status['converged'],
                            physical_validation=result.run_status['physical_validation']))
    assert reports[0]['Q'] != reports[1]['Q'], 'the supplied field must affect the forward solve'
    (args.output / 'summary.json').write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports))


if __name__ == '__main__':
    main()
