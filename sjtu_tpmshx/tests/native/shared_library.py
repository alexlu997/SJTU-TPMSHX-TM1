"""Find the full native library for its consumer tests."""
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def library_path():
    """Keep the configured path and the required-library failure policy."""
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    name = 'tpmshx_solver_shared.dll' if os.name == 'nt' else 'libtpmshx_solver_shared.dylib'
    path = Path(os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY',
        ROOT / '.cache/native-deps/build' / ('pilot-' + host) / name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'native full library unavailable: {path}')
        pytest.skip(f'native full library unavailable: {path}')
    return path
