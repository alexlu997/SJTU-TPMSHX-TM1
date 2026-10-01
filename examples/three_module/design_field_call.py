"""Change a prepared effective-conductivity field; no private solver mutation.

This uses the full forward solver. Gradients/adjoints are not implemented.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import numpy as np

from sjtu_tpmshx.domain.compute_config import ComputeConfig, ZoneInputConfig
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.case_io import save_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.metrics_io import save_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    config = ComputeConfig.from_json(Path(__file__).with_name('air_2d.json'))
    config = replace(config, zones=ZoneInputConfig(enabled=True, axis='continuous', config=dict(
        x_decision=[config.geometry.L_cell_mm]*4 + [config.geometry.t_wall_mm]*4,
        n_ctrl_x=2, n_ctrl_y=2, symmetric_y=False, spline_order=1,
        L_bounds=[4., 8.], t_bounds=[.3, .6])))
    base = prepare_case(config, case_id='uniform-effective-field')
    dx = np.asarray(base.grid['dx'])
    x_fraction = (np.cumsum(dx) - dx/2) / dx.sum()
    conductivity = np.asarray(base.design_fields['K_ss_arr']) * (.5 + .5*x_fraction[:, None])
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
                            envelope_valid=result.run_status['envelope_valid']))
    assert reports[0]['Q'] != reports[1]['Q'], 'the supplied field must affect the forward solve'
    (args.output / 'summary.json').write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports))


if __name__ == '__main__':
    main()
