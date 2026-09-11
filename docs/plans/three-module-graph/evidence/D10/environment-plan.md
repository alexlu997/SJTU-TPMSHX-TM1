# D10/D20/E00 coordinated dependency change

The current configured shared Python environment matches the original
71-package lock and passes pip check, but h5py/PyYAML are absent. Local HDF5
and YAML runtime tests cannot pass in it. Static source and test preparation
is allowed; no missing-dependency test is counted as passed.

Proposed additions: h5py==3.15.1 and PyYAML==6.0.3, both already published
with Python 3.12/3.13 platform wheels. Versions verified against their official
PyPI release pages:
https://pypi.org/project/h5py/3.15.1/
https://pypi.org/project/PyYAML/6.0.3/

The main lock gains exactly these two packages; the server lock includes the
main lock. The optional io extra declares them. A separate small offline lock
covers source-based postprocessing/I/O tests without installing this repository
as the full solver distribution or claiming a minimal wheel distribution.
The existing full-package install metadata remains unchanged apart from io.
The new isolated GitHub job runs the real minimal dependency list and pip
check. Existing macOS/Windows CI remains intact and picks up the added I/O tests.

For local verification, request a NEW dependency-only environment at
/private/tmp/sjtu-tm1-io-venv, installed from the updated exact lock, plus the
worktree .venv-path pointing to it. The shared environment is never rebuilt.
Run exact-lock and pip checks before any tests, then prewarm through the
existing small real integration tests and execute YAML/HDF5 roundtrips.
This environment creation requires explicit user authorization under AGENTS.md;
source changes and CI environment setup do not grant that local permission.

User authorization received; the new environment was installed successfully and both exact-lock (73 active packages) and pip check passed. Real YAML/HDF5 and offline metrics: 7 passed in 11.90 s, native exit 0. Minimal remote CI remains pending. Required remote check:
three-module / minimal-postprocess, in addition to existing ci platform jobs.
