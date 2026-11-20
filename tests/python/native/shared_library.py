"""Find the CMake-built libraries for native consumer tests."""
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
HOST, PREFIX, SUFFIX = ('windows-x64', '', '.dll') if os.name == 'nt' else (
    'macos-arm64', 'lib', '.dylib')
PILOT = ROOT / '.cache/native-deps/build' / f'pilot-{HOST}'


def library_path():
    """Keep the configured path and the required-library failure policy."""
    return _required(Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY',
        PILOT / f'{PREFIX}tpmshx_solver_shared{SUFFIX}')))


def kernel_test_path():
    return _required(PILOT / f'{PREFIX}tpmshx_kernel_test{SUFFIX}')


def _required(path):
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'native library unavailable: {path}')
        pytest.skip(f'native library unavailable: {path}')
    return path
