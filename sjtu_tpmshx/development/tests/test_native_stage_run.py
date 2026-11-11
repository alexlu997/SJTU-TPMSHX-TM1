"""Compare the independent native stage caller with the existing workflow."""
from dataclasses import asdict
import json
import os
from pathlib import Path

import numpy as np
import pytest

from sjtu_tpmshx.compute import compute
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig
from sjtu_tpmshx.shared.domain.module_ports import RunControl
from sjtu_tpmshx.shared.domain.portable_data import mutable_data


@pytest.mark.slow
def test_independent_stage_fields_metrics_and_qualification():
    root = Path(__file__).resolve().parents[3]
    evidence = Path(os.environ.get('TPMSHX_STAGE_RESULT_DIR', root / '.cache/native-deps/build/stage-result'))
    if not (evidence / 'fields.tsv').is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS'):
            pytest.fail('Run build_native_dependencies.py check-stages before this test')
        pytest.skip('the installed stage caller has not run')
    config = ComputeConfig.from_dict(json.loads((root / 'examples/three_module/air_2d.json').read_text()))
    _, result, performance = compute(config, control=RunControl(cpu_threads=2))
    records = [line.split('\t') for line in (evidence / 'fields.tsv').read_text().splitlines()]
    assert len(records) == len(result.fields)
    assert {name for name, _, _ in records} == set(result.fields)
    for name, nx, ny in records:
        actual = np.fromfile(evidence / (name + '.bin')).reshape(int(nx), int(ny))
        expected = np.asarray(result.fields[name])
        np.testing.assert_array_equal(actual.view(np.uint64), expected.view(np.uint64), err_msg=name)
    report = json.loads((evidence / 'metrics.json').read_text())
    assert report['metrics'] == {name: asdict(value) for name, value in performance.metrics.items()}
    qualification = mutable_data(performance.qualification)
    assert qualification['source_result_id'] == result.result_id
    assert report['qualification']['source_result_id'] == report['source_result_id']
    qualification['source_result_id'] = report['source_result_id']
    assert report['qualification'] == qualification
