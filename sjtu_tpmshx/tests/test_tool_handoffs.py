"""File handoffs and process outcomes, without launching BO or CFD."""
import csv
import json
from concurrent.futures import Future

import numpy as np
import pytest

from sjtu_tpmshx.models.screening import DEFAULT_CONFIG
from sjtu_tpmshx.optimization import parallel_runner as parallel
from sjtu_tpmshx.optimization import export_ntop_csv as ntop
from sjtu_tpmshx.validation.cases import verify_pareto_3d as verify


@pytest.mark.parametrize('dimension', [16, 36])
def test_export_and_verifier_restore_the_same_named_decisions(tmp_path, monkeypatch, dimension):
    values = {f'x{i}': float(i + 1) for i in range(dimension)}
    values.update(Q_W_per_m=1234., dP_Pa=567.)
    path = tmp_path / 'pareto.csv'
    with path.open('w', newline='') as target:
        writer = csv.DictWriter(target, list(reversed(values)))
        writer.writeheader()
        writer.writerow(values)
    captured = []
    monkeypatch.setattr(ntop, 'export_decision_vector',
                        lambda x, *a, **kw: captured.append(x))
    cfg = {**DEFAULT_CONFIG, 'n_ctrl_x': 6 if dimension == 36 else 4,
           'n_ctrl_y': 6 if dimension == 36 else 4}
    ntop.export_pareto_row(str(path), 0, str(tmp_path / 'out'), config=cfg)
    expected, q, dp = verify._load_pareto_row(str(path), 0, dimension)
    np.testing.assert_array_equal(captured[0], expected)
    assert (q, dp) == (1234., 567.)


def test_verification_requires_original_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, 'evaluate_3d', lambda *a, **kw: pytest.fail('solver launched'))
    with pytest.raises(ValueError, match='original config.json'):
        verify.main(['--pareto', str(tmp_path / 'pareto.csv')])


@pytest.mark.parametrize('config', [{}, [], {k: v for k, v in DEFAULT_CONFIG.items() if k != 'L_domain'}])
def test_export_rejects_incomplete_geometry_metadata(tmp_path, monkeypatch, config):
    path = tmp_path / 'pareto.csv'
    path.write_text(','.join([*(f'x{i}' for i in range(16)), 'Q_W_per_m', 'dP_Pa'])
                    + '\n' + ','.join(['1'] * 18) + '\n')
    monkeypatch.setattr(ntop, 'export_decision_vector', lambda *a, **kw: pytest.fail('invalid metadata exported'))
    with pytest.raises(ValueError, match='configuration'):
        ntop.export_pareto_row(str(path), 0, str(tmp_path / 'out'), config=config)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('failed_seeds', [{43}, {42, 43}, set()])
def test_multiseed_config_actual_members_and_failed_members(tmp_path, monkeypatch, failed_seeds):
    class Executor:
        def __init__(self, **kwargs):
            assert kwargs['initializer'] is parallel.set_worker_thread_caps
            assert kwargs['mp_context'].get_start_method() == 'spawn'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, seed, cfg, *args):
            future = Future()
            if seed in failed_seeds:
                future.set_exception(RuntimeError(f'failed seed {seed}'))
            else:
                x, f = np.ones((1, 16)), np.array([[-100., 20.]])
                future.set_result(dict(seed=seed, config=cfg, X=x, F=f,
                                       history_X=x, history_F=f, history_errors=[None],
                                       n_evals=1, termination_reason='completed'))
            return future

    monkeypatch.setattr(parallel, 'ProcessPoolExecutor', Executor)
    output = tmp_path / 'multiseed'
    result = parallel.run_qnehvi_multiseed(seeds=[42, 43], config={'u_A': 7.},
                                          save_dir_base=str(output), verbose=False)
    assert set(result['seeds_used']) == {42, 43} - failed_seeds
    assert set(result['failed_seeds']) == failed_seeds
    assert result['complete'] is (not failed_seeds)
    assert result['seeds_requested'] == [42, 43]
    assert json.loads((output / 'config.json').read_text())['u_A'] == 7.
    status = json.loads((output / 'multiseed_status.json').read_text())
    assert set(map(int, status['failed_seeds'])) == failed_seeds
    assert verify._load_run_cfg(str(output / 'pareto_merged.csv'))['u_A'] == 7.
    assert result['X'].shape[1] == 16
    assert len(next(csv.reader((output / 'pareto_merged.csv').open()))) == 18


@pytest.mark.parametrize('default_name', [False, True])
def test_existing_multiseed_archive_rejected_before_process_launch(tmp_path, monkeypatch, default_name):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(parallel.time, 'strftime', lambda *a: 'fixed-time')
    output = tmp_path / ('opt_qnehvi_multiseed_fixed-time' if default_name else 'existing')
    output.mkdir()
    original = {'config.json': b'{"original": true}', 'pareto_merged.csv': b'previous front\n'}
    for name, content in original.items():
        (output / name).write_bytes(content)
    monkeypatch.setattr(parallel, 'ProcessPoolExecutor',
                        lambda **kwargs: pytest.fail('existing archive launched processes'))
    with pytest.raises(FileExistsError):
        parallel.run_qnehvi_multiseed(seeds=[42],
            save_dir_base=None if default_name else str(output), verbose=False)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original


def test_seed_helper_leaves_new_output_directory_to_optimizer(tmp_path, monkeypatch):
    pytest.importorskip('botorch', reason='BO execution requires the optional server lock')
    from sjtu_tpmshx.optimization import optimizer_qnehvi as bo
    # Exercise the real helper and optimizer; only numerical evaluation and
    # process-local thread caps are replaced in this in-process handoff test.
    monkeypatch.setattr(parallel, 'set_worker_thread_caps', lambda: None)
    calls = []

    def evaluate(x, cfg):
        calls.append(x.copy())
        return -10., 20., 1.

    monkeypatch.setattr(bo, 'evaluate_design', evaluate)
    result = parallel._seed_subprocess_main(42, None, 2, 0, 1, 1, str(tmp_path), .01, 3, False)
    output = tmp_path / 'seed_042'
    assert result['save_dir'] == str(output)
    assert result['termination_reason'] == 'completed' and result['n_evals'] == len(calls) == 2
    assert json.loads((output / 'config.json').read_text()) == json.loads(json.dumps(result['config']))
    assert len((output / 'history.csv').read_text().splitlines()) == 3
    assert len((output / 'pareto_final.csv').read_text().splitlines()) == 3


@pytest.mark.parametrize('seeds', [[], [42, 42]])
def test_invalid_seed_membership_rejected(seeds, tmp_path):
    with pytest.raises(ValueError, match='seed'):
        parallel.run_qnehvi_multiseed(seeds=seeds, save_dir_base=str(tmp_path))


@pytest.mark.parametrize('complete', [False, True])
def test_both_multiseed_cli_exits_reflect_partial_failure(monkeypatch, complete):
    from sjtu_tpmshx.runs import run_production_qnehvi_parallel as production
    result = dict(X=np.empty((0, 16)), F=np.empty((0, 2)), n_evals=0,
                  wall_time_s=0., save_dir='unused', seeds_used=[], complete=complete)
    monkeypatch.setattr(parallel, 'run_qnehvi_multiseed', lambda **kw: result)
    assert parallel.main(['--quiet']) == (0 if complete else 1)
    assert production.main(['--quiet']) == (0 if complete else 1)


_SINGLE_SEED_CLI_MODULES = [
    'sjtu_tpmshx.runs.run_production_qnehvi',
    'sjtu_tpmshx.runs.run_3d_qnehvi_fast',
    'sjtu_tpmshx.optimization.optimizer_qnehvi',
]


@pytest.mark.parametrize('module', _SINGLE_SEED_CLI_MODULES)
@pytest.mark.parametrize('reason,count,exit_code', [
    ('completed', 1, 0), ('plateau', 1, 0),
    ('completed', 0, 1), ('plateau', 0, 1),
    ('cancelled', 1, 1), ('cancelled', 0, 1),
])
def test_single_seed_cli_uses_optimizer_outcome(module, reason, count, exit_code, capsys):
    import importlib
    import runpy
    import sys
    import warnings

    entry = importlib.import_module(module)
    assert callable(entry.main)
    result = dict(X=np.ones((count, 16)), F=np.tile([-10., 20.], (count, 1)),
                  n_evals=2, save_dir='unused', termination_reason=reason)
    calls = []

    def optimizer(**kwargs):
        calls.append(kwargs)
        assert 'cancel_check' not in kwargs  # These CLI presets do not add a cancellation source.
        return result

    def enter_main(frame, event, arg):
        if (event == 'call' and frame.f_globals.get('__name__') == '__main__'
                and frame.f_code.co_name == 'main'):
            # Patch only the costly boundary after runpy loads the unmodified
            # command, including the optimizer module's own function definition.
            frame.f_globals['run_qnehvi'] = optimizer

    previous = sys.getprofile()
    try:
        sys.setprofile(enter_main)
        # Each real main changes the global warning filter; restore it after this command.
        with warnings.catch_warnings(), pytest.raises(SystemExit) as caught:
            runpy.run_path(entry.__file__, run_name='__main__')
    finally:
        sys.setprofile(previous)
    assert caught.value.code == exit_code
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert reason in output
    if not count:
        assert 'no valid Pareto solutions' in output


@pytest.mark.parametrize('module', _SINGLE_SEED_CLI_MODULES)
@pytest.mark.parametrize('error_type', [RuntimeError, KeyboardInterrupt])
def test_single_seed_cli_propagates_optimizer_errors(module, error_type, monkeypatch):
    import importlib
    import warnings

    entry = importlib.import_module(module)
    error = error_type('injected optimizer interruption')

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(entry, 'run_qnehvi', fail)
    # Restore the warning filter changed by the real main even on interruption.
    with warnings.catch_warnings(), pytest.raises(error_type) as caught:
        entry.main()
    assert caught.value is error
