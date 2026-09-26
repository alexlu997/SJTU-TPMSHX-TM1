"""Execute the Windows runners with recorded, non-computing Python modules."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_PWSH = shutil.which('pwsh')


def _run_runner(tmp_path, script, lock=None):
    command = [_PWSH, '-NoProfile', '-File', str(tmp_path / 'scripts' / script)]
    if lock is not None:
        command += ['-LockFile', lock]
    with subprocess.Popen(command, cwd=tmp_path, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired as error:
            returncode = process.poll()
            process.kill()
            stdout, stderr = process.communicate()
            calls_path = tmp_path / 'calls.jsonl'
            calls = calls_path.read_text(encoding='utf-8') if calls_path.exists() else '(none)'
            pytest.fail(
                f'Runner timed out after {error.timeout}s: {command!r}\n'
                f'Return code before forced cleanup: {returncode!r}\n'
                f'Completed module calls:\n{calls}\n'
                f'stdout: {stdout!r}\nstderr: {stderr!r}',
            )
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


@pytest.mark.skipif(os.name != 'nt' or not _PWSH, reason='Windows PowerShell runner')
@pytest.mark.parametrize('script', ['run_tests_fast.ps1', 'run_tests_server.ps1'])
def test_runner_missing_environment_fails_before_python(tmp_path, script):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    for runner in ('run_tests_fast.ps1', 'run_tests_server.ps1'):
        shutil.copyfile(_ROOT / 'scripts' / runner, scripts / runner)
    result = _run_runner(tmp_path, script)
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'Missing .venv-path.' in result.stdout + result.stderr


@pytest.mark.skipif(os.name != 'nt' or not _PWSH, reason='Windows PowerShell runner')
@pytest.mark.parametrize('script', ['run_tests_fast.ps1', 'run_tests_server.ps1'])
@pytest.mark.parametrize('lock,failed_step', [
    (None, None),
    ('requirements-lock-server.txt', None),
    ('requirements-lock-server.txt', 'lock'),
    ('requirements-lock.txt', 'pip'),
    ('requirements-lock.txt', 'pytest'),
])
def test_runner_uses_selected_lock_and_stops_before_tests(tmp_path, script, lock, failed_step):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    for runner in ('run_tests_fast.ps1', 'run_tests_server.ps1'):
        shutil.copyfile(_ROOT / 'scripts' / runner, scripts / runner)
    (tmp_path / '.venv-path').write_text(sys.executable, encoding='utf-8')
    package = tmp_path / 'sjtu_tpmshx' / 'runs' / 'tools'
    package.mkdir(parents=True)
    for directory in (package, package.parent, package.parent.parent):
        (directory / '__init__.py').touch()
    modules = {
        'lock': package / 'check_locked_environment.py',
        'pip': tmp_path / 'pip.py',
        'pytest': tmp_path / 'pytest.py',
    }
    for name, path in modules.items():
        path.write_text(
            'import json, sys\n'
            'from pathlib import Path\n'
            f'print({name!r}, flush=True)\n'
            'with Path("calls.jsonl").open("a", encoding="utf-8") as output:\n'
            f'    output.write(json.dumps([{name!r}, sys.argv[1:]]) + "\\n")\n'
            f'raise SystemExit({2 if name == failed_step else 0})\n',
            encoding='utf-8',
        )
    calls_path = tmp_path / 'calls.jsonl'
    result = _run_runner(tmp_path, script, lock)
    assert calls_path.exists(), result.stdout + result.stderr
    calls = [json.loads(line) for line in calls_path.read_text(encoding='utf-8').splitlines()]
    assert calls[0] == ['lock', [lock or 'requirements-lock.txt']]
    expected = ['lock'] if failed_step == 'lock' else ['lock', 'pip']
    if failed_step in (None, 'pytest'):
        expected.append('pytest')
    assert [call[0] for call in calls] == expected
    assert (result.returncode == 0) == (failed_step is None), result.stdout + result.stderr
    if len(calls) > 1:
        assert calls[1] == ['pip', ['check']]
    if calls[-1][0] == 'pytest':
        arguments = ['sjtu_tpmshx/tests/', '-q', '-n']
        arguments += (['32', '--dist', 'worksteal', '-m', 'not heavy']
                      if script == 'run_tests_fast.ps1' else
                      ['64', '--dist', 'worksteal', '--durations=15'])
        assert calls[-1] == ['pytest', arguments]
    if failed_step == 'pytest':
        assert result.returncode == 1, result.stdout + result.stderr
