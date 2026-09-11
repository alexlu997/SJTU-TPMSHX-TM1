"""Port helpers keep TM1 run ownership and validate before copying results."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name == 'nt', reason='The local pull helper uses bash.')
def test_pull_uses_configured_environment_before_scp(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'scripts/port_retest_pull.sh'
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    metrics = tmp_path / 'metrics.json'
    metrics.write_text(json.dumps(dict(
        decision_dim=4, hv_gain_pct=1.5, uniform_dominated_frac=.5,
        budget={'graded': 10}, wall_seconds=3600)))
    stubs = {
        'scp': '#!/bin/sh\nprintf "%s\\n" "$@" > scp-args.txt\n'
               'mkdir -p reports/port_dim_retest/c4s7\n'
               'cp metrics.json reports/port_dim_retest/c4s7/port_metrics.json\n',
        'python': '#!/bin/sh\nexit 99\n',
        'configured-python': '#!/bin/sh\n'
            'if [ "$1" = "-m" ]; then\n'
            '  printf "%s\\n" "$*" >> environment-calls.txt\n'
            '  if [ "$2" = "sjtu_tpmshx.runs.tools.check_locked_environment" ]; then\n'
            '    exit "$TM1_TEST_LOCK_EXIT"\n'
            '  fi\n'
            '  exit "$TM1_TEST_PIP_EXIT"\n'
            'fi\n'
            f'exec {shlex.quote(sys.executable)} "$@"\n',
    }
    for name, contents in stubs.items():
        executable = binaries / name
        executable.write_text(contents)
        executable.chmod(0o755)
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
               PORT_WORKDIR='/srv/tpmshx', TM1_TEST_LOCK_EXIT='7', TM1_TEST_PIP_EXIT='0')
    pointer = tmp_path / '.venv-path'
    pointer.write_text(str(tmp_path / 'missing-python') + '\n')

    def run():
        return subprocess.run(['bash', str(script), 'example@server'],
                              cwd=tmp_path, env=env, capture_output=True, text=True)

    assert run().returncode == 1
    assert not (tmp_path / 'scp-args.txt').exists()
    pointer.write_text(str(binaries / 'configured-python') + '\n')
    assert run().returncode == 7
    assert not (tmp_path / 'reports').exists()
    env['TM1_TEST_LOCK_EXIT'] = '0'
    env['TM1_TEST_PIP_EXIT'] = '11'
    assert run().returncode == 11
    assert not (tmp_path / 'reports').exists()
    env['TM1_TEST_PIP_EXIT'] = '0'
    result = run()
    assert result.returncode == 0, result.stderr
    assert 'HV gain  +1.50%' in result.stdout
    assert (tmp_path / 'scp-args.txt').read_text().splitlines() == [
        '-r', 'example@server:/srv/tpmshx/SJTU-TPMSHX-TM1/reports/port_dim_retest', 'reports/']
    assert (tmp_path / 'environment-calls.txt').read_text().splitlines() == [
        '-m sjtu_tpmshx.runs.tools.check_locked_environment',
        '-m sjtu_tpmshx.runs.tools.check_locked_environment', '-m pip check',
        '-m sjtu_tpmshx.runs.tools.check_locked_environment', '-m pip check']


def test_server_status_does_not_reuse_v2_logs_or_pids(tmp_path):
    scripts = Path(__file__).resolve().parents[2] / 'scripts'
    logs = tmp_path / 'logs'
    current = logs / 'SJTU-TPMSHX-TM1'
    current.mkdir(parents=True)
    (logs / 'c4s7.log').write_text('[PORT] V2_ONLY DONE\n')
    (current / 'c4s7.log').write_text('[PORT] TM1 current log\n')
    pids = tmp_path / 'pids'
    pids.mkdir()
    (pids / 'c4s7.pid').write_text(str(os.getpid()))
    command = (['powershell', '-NoProfile', '-File', str(scripts / 'port_retest_server.ps1')]
               if os.name == 'nt' else ['bash', str(scripts / 'port_retest_server.sh')])
    result = subprocess.run([*command, 'status'], capture_output=True, text=True,
                            env=dict(os.environ, PORT_WORKDIR=str(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert 'TM1 current log' in result.stdout
    assert 'V2_ONLY' not in result.stdout
    if os.name == 'nt':
        assert 'UNKNOWN' in result.stdout
        assert 'RUNNING' not in result.stdout
