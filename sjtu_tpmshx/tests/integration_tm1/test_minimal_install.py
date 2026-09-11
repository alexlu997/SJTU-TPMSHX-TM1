"""Actual numerical archives consumed in the isolated minimal CI environment."""
import os
from pathlib import Path

import numpy as np
import pytest


def test_real_archives_in_minimal_environment():
    directory = os.environ.get('TM1_REAL_HANDOFF_DIR')
    if directory is None:
        pytest.skip('requires real producer files and the minimal environment')
    from sjtu_tpmshx.runs.tools.check_three_module_environment import main
    from sjtu_tpmshx.io.result_io import load_result
    from sjtu_tpmshx.io.metrics_io import load_metrics
    from sjtu_tpmshx.postprocess.api import evaluate
    main()
    archives = list(Path(directory).glob('**/handoff/results.h5'))
    assert len(archives) == 2, 'require both real 2D and 3D producer archives'
    units = set()
    for archive in archives:
        result = load_result(archive)
        assert result.run_status['converged'] is True
        actual = evaluate(result).metrics
        expected = load_metrics(archive.with_name('metrics.json')).metrics
        assert actual.keys() == expected.keys()
        for name, metric in actual.items():
            baseline = expected[name]
            assert metric.spec == baseline.spec
            assert metric.status == baseline.status
            assert metric.reason == baseline.reason
            if metric.value is None:
                assert baseline.value is None
            else:
                np.testing.assert_allclose(metric.value, baseline.value,
                                           rtol=1e-10, atol=1e-10)
        assert actual['Q'].status == 'available'
        units.add(actual['Q'].spec.unit)
    assert units == {'W/m', 'W'}
    main()  # Verify actual evaluation did not import a numerical backend.
