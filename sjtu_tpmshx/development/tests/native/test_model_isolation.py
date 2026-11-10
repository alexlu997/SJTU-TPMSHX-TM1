"""Keep preparation and solver model images independent in fresh processes."""
import json
import os
from pathlib import Path
import subprocess
import tomllib

import pytest

from sjtu_tpmshx.development.tests.native import model_isolation as isolation
from sjtu_tpmshx.development.tests.native.shared_library import library_path
from sjtu_tpmshx.development.tests.native.test_native_execution import _config
from sjtu_tpmshx.shared.models import _native_preparation


@pytest.fixture(scope='module')
def model_libraries():
    solver = library_path().resolve()
    try:
        preparation = Path(_native_preparation._library_path())
    except (FileNotFoundError, RuntimeError) as error:
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1' or 'TPMSHX_PREPARATION_LIBRARY' in os.environ:
            pytest.fail(str(error))
        pytest.skip(str(error))
    return {'solver': str(solver), 'preparation': str(preparation)}


def _run_child(python, directory, plan, environment):
    directory.mkdir()
    plan_path = directory / 'plan.json'
    isolation.write_json(plan_path, plan)
    process = subprocess.run([str(python), '-m', 'sjtu_tpmshx.development.tests.native.model_isolation', str(plan_path)],
        cwd=isolation.ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    (directory / 'run.log').write_text(process.stdout, encoding='utf-8')
    report_path = directory / 'report.json'
    assert process.returncode == 0 and report_path.is_file(), (directory, process.stdout)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['state'] == 'passed', report
    return report


@pytest.mark.parametrize('oracle_position', ['none', 'before', 'after'])
def test_cold_model_images_keep_serial_results_and_physical_gates(tmp_path, model_libraries, monkeypatch, oracle_position):
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.shared.io.case_io import save_case
    from sjtu_tpmshx.shared.io.hdf5_data import read_record
    from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
    from sjtu_tpmshx.solvers.backends.cpp.full_3d_capture import capture_result
    from sjtu_tpmshx.development.tests.native.full_result_audit import physical_gates

    python = isolation.configured_python()
    monkeypatch.setenv('TPMSHX_PREPARATION_LIBRARY', model_libraries['preparation'])
    case = prepare_case(_config(3, False), case_id='model-isolation')
    case_path = tmp_path / 'case.h5'
    save_case(case, case_path)
    with (isolation.ROOT / 'sjtu_tpmshx/solvers/native/dependencies-lock.toml').open('rb') as source:
        spec = tomllib.load(source)['sources']['coolprop']
    coolprop = {'version': spec['version'], 'revision': spec['commit']}
    environment = dict(os.environ, TPMSHX_PREPARATION_LIBRARY=model_libraries['preparation'],
        PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        VECLIB_MAXIMUM_THREADS='1', MKL_NUM_THREADS='1',
        MPLCONFIGDIR=str(isolation.ROOT / '.cache/model-isolation/matplotlib'),
        XDG_CACHE_HOME=str(isolation.ROOT / '.cache/model-isolation/xdg'))
    jobs = [('prep-reference', []), ('solver-reference', [])]
    jobs += [(mode, order) for order in (['solver', 'preparation'], ['preparation', 'solver'])
             for mode in ('pair', 'prep-pair', 'solver-pair')]
    reports = []
    for index, (mode, order) in enumerate(jobs):
        plan = dict(model_libraries, case=str(case_path), mode=mode, order=order,
                    oracle_position=oracle_position, coolprop=coolprop)
        reports.append(_run_child(python, tmp_path / f'{index}-{mode}', plan, environment))

    references = {value['kind']: value for report in reports[:2] for value in report['results'].values()}
    cfg, prepared = build_execution_inputs(case)
    expected_raw = read_record(references['solver']['raw'], isolation.RawRecord, isolation.RAW_KIND).data
    for report in reports:
        for value in report['results'].values():
            if value['kind'] == 'preparation':
                isolation.same(value['valid'], references['preparation']['valid'])
                isolation.same(value['rejected'], references['preparation']['rejected'])
            else:
                raw = read_record(value['raw'], isolation.RawRecord, isolation.RAW_KIND).data
                isolation.same(raw, expected_raw)
                isolation.same(value['rejected_water'], references['solver']['rejected_water'])
                physical_gates(capture_result(case, cfg, prepared, raw, value['abi']))
