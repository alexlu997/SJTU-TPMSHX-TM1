"""Rebuild native thermal targets after changes to their local headers."""
import os
from pathlib import Path
import subprocess

import pytest


_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name == 'nt', reason='GNU Make runs on macOS; NMake runs in Windows CI')
@pytest.mark.parametrize('target,header,source', [
    ('enthalpy_sweeps.o', 'native/src/energy_fv_rows.hpp', 'native/src/enthalpy_sweeps.cpp'),
    ('enthalpy_sweeps.o', 'native/include/tpmshx/conservative_energy.hpp', 'native/src/enthalpy_sweeps.cpp'),
    ('temperature_driver.o', 'native/src/temperature_run_state.hpp', 'native/src/temperature_driver.cpp'),
])
def test_header_change_rebuilds_native_target(tmp_path, target, header, source):
    output = tmp_path / target
    output.touch()
    command = ['make', '-f', 'native/Makefile', '-n', f'BUILD_DIR={tmp_path}', str(output)]
    current = subprocess.run(command, cwd=_ROOT, check=True, capture_output=True, text=True)
    assert source not in current.stdout
    changed = subprocess.run([*command, '-W', header], cwd=_ROOT,
                             check=True, capture_output=True, text=True)
    assert source in changed.stdout


@pytest.mark.parametrize('target,header', [
    ('$(BUILD_DIR)/enthalpy_sweeps.obj', 'native/src/energy_fv_rows.hpp'),
    ('$(BUILD_DIR)/enthalpy_sweeps.obj', 'native/include/tpmshx/conservative_energy.hpp'),
    ('$(BUILD_DIR)/temperature_driver.obj', 'native/src/temperature_run_state.hpp'),
])
def test_nmake_rule_tracks_shared_headers(target, header):
    lines = (_ROOT / 'native/Makefile.msvc').read_text(encoding='utf-8').replace('\\', '/').splitlines()
    dependencies = next(line.split(':', 1)[1].split() for line in lines
                        if line.startswith(target + ':'))
    assert header in dependencies
