# 2D preparation extraction — partial P20/I20/I55

Base `f5573e2`; branch `codex/tm1/p20-repair`. The input parser, physical grid
construction, port-overlap primitives and sigmoid model now have single pure
implementations. Existing pipeline/solver entry points delegate to them.
`prepare_case` returns actual SI grids, opening fractions, prepared zone fields,
fixed inputs and model references without initializing a numerical backend.
The original config snapshot retains its explicitly named legacy input units;
prepared millimetre geometry fields are converted to metre fields.

Environment: `/Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python` from worktree
root; exact lock 71 packages and pip check pass. Every pytest run uses
`MPLCONFIGDIR=.cache/matplotlib XDG_CACHE_HOME=.cache`.

After `python -m pytest -q`:

- `sjtu_tpmshx/tests/test_pipeline_reexports.py sjtu_tpmshx/tests/test_port_grid_alignment_2d.py sjtu_tpmshx/tests/test_grid_schema.py`: 37 passed / 12 failed, native exit 1. The extraction accidentally changed the existing pipeline breakpoint sets to tuples. Fixed the adapter to preserve sets; portable CaseData uses tuples. Existing tests were not changed.
- `sjtu_tpmshx/tests/test_port_grid_alignment_2d.py sjtu_tpmshx/tests/test_import_layering.py sjtu_tpmshx/tests/preprocess/test_2d_tm1.py`: 28 passed, native exit 0, 11.90 seconds.
- The preceding three files plus `sjtu_tpmshx/tests/test_sigmoid_field.py`: 30 passed / 1 failed, native exit 1, 33.91 seconds. Failure was a new exact-equality assertion on floating point port overlap, reproduced independently (1 failed, exit 1). The check now verifies integrated physical opening width at 1e-13 relative tolerance; the raw fractions were not modified. Sigmoid tests passed with one preserved Nu-range warning.
- `sjtu_tpmshx/tests/preprocess/test_2d_tm1.py sjtu_tpmshx/tests/test_import_layering.py`: 3 passed, native exit 0, 1.91 seconds. Full ports, partial ports and 1D zones; immutable effective grids, SI zone data, source detachment; clean-process preparation without solvers/pipelines/Numba/Qt.
- `python -m ruff check sjtu_tpmshx`: all checks pass, native exit 0. Existing public re-exports retained explicitly.

No full 2D solve comparison or independent review/remote CI yet. Runtime
consumption and per-mode contract checks remain required; P20/I20 are not done.
Formal YAML/HDF5 dependencies are absent in the configured environment; VTK
is present. No dependency was installed or environment rebuilt.
