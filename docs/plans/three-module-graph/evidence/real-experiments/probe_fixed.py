"""Pair existing fixed-manifest configs through each checkout's real pipeline.

Invoke with runpy from the repository root; output is a new local directory.
The manifest and config snapshots are read-only inputs, never published here.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from sjtu_tpmshx.controllers.compute_pipeline import pipeline_for
from sjtu_tpmshx.domain.compute_config import ComputeConfig


def encode(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


parser = argparse.ArgumentParser()
parser.add_argument('manifest', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
jobs = manifest['jobs']
assert len(jobs) == 166 and [j['index'] for j in jobs] == list(range(1, 167))
assert len({j['id'] for j in jobs}) == 166
configs = []
for job in jobs:
    snapshot = args.manifest.parent / 'configs' / Path(job['config']).name
    assert json.loads(snapshot.read_text()) == json.loads(Path(job['config']).read_text())
    configs.append(ComputeConfig.from_json(str(snapshot)))
args.output.mkdir(exist_ok=False)
(args.output / 'provenance.json').write_text(json.dumps(dict(
    source_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    interpreter=sys.executable, manifest=str(args.manifest.resolve()),
    expected=166, ids=[j['id'] for j in jobs]), indent=2)+'\n')
failed = False
for job, cfg in zip(jobs, configs):
    row = dict(id=job['id'], dimension=job['dimension'], config=asdict(cfg))
    try:
        result = pipeline_for(cfg).run()
        row.update(execution='completed', converged=bool(result.converged),
                   raw_metrics={k: getattr(result, k) for k in (
                       'Q_W', 'dP_A_Pa', 'dP_B_Pa', 'T_out_A_K', 'T_out_B_K')},
                   diagnostics=result.diagnostics, warnings=list(result.warnings or []))
    except Exception as exc:
        failed = True
        row.update(execution='failed', exception=type(exc).__name__, message=str(exc))
    (args.output / (job['id']+'.json')).write_text(
        json.dumps(row, default=encode, indent=2)+'\n')
    print(job['id'], row['execution'], row.get('converged'), flush=True)
sys.exit(1 if failed else 0)
