"""Run two full-solver parameter cases using public module/file APIs."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from sjtu_tpmshx.domain.compute_config import ComputeConfig
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
    baseline = ComputeConfig.from_json(Path(__file__).with_name('air_2d.json'))
    reports = []
    for factor in (1., 1.2):
        velocity = baseline.fluid_A.u_mps * factor
        name = f'u-{velocity:g}'
        folder = args.output / name
        folder.mkdir(parents=True, exist_ok=True)
        config = replace(baseline, fluid_A=replace(baseline.fluid_A, u_mps=velocity))
        case = prepare_case(config, case_id=name)
        result = run_case(case)
        metrics = evaluate(result)
        save_case(case, folder / 'case.yaml')
        save_result(result, folder / 'results.h5')
        save_metrics(metrics, folder / 'metrics.json')
        reports.append(dict(case_id=name, Q=metrics.metrics['Q'].value,
                            Q_unit=metrics.metrics['Q'].spec.unit,
                            converged=result.run_status['converged'],
                            envelope_valid=result.run_status['envelope_valid']))
    (args.output / 'summary.json').write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports))


if __name__ == '__main__':
    main()
