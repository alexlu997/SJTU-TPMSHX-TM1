"""Run from the repository root: python -m examples.three_module.external_design input.json output-dir.

Input is a DesignCase JSON record (temperatures K, absolute pressures Pa,
mass flows kg/s). Outputs use total W for this prescribed-velocity design mode.
"""
import argparse
import json
from pathlib import Path

from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.preprocess.api import prepare_quick_design
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.io.case_io import save_case, load_case
from sjtu_tpmshx.io.result_io import save_result
from sjtu_tpmshx.io.metrics_io import save_metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--arrangement', choices=('cross', 'counter'), default='cross')
    parser.add_argument('--prop-model', choices=('const', 'mean'), default='const')
    args = parser.parse_args(argv)
    point = DesignCase(**json.loads(args.input.read_text()))
    case = prepare_quick_design(point, 'Diamond', 7., .5, .084, .05, args.arrangement,
                               case_id='external-design', prop_model=args.prop_model, height=.07)
    args.output.mkdir(parents=True, exist_ok=True)
    save_case(case, args.output / 'case.yaml')
    result = run_case(load_case(args.output / 'case.yaml'))
    save_result(result, args.output / 'results.h5')
    metrics = evaluate(result)
    save_metrics(metrics, args.output / 'metrics.json')
    print(f"Q_hot = {metrics.metrics['Q'].value} W; numerical convergence = {result.run_status['converged']}")
    return 0 if result.run_status['converged'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
