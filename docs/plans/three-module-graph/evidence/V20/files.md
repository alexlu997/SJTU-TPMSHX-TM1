# Real 2D and 3D file handoff evidence

Local source based on `1139a0b` plus coordinated IO integration, with the
explicitly authorized `/private/tmp/sjtu-tm1-io-venv/bin/python` environment.
Exact 73 active packages and pip check both passed; installation exited 0.
The previous shared environment was not modified.

Command (worktree-local MPLCONFIGDIR/XDG_CACHE_HOME):
`python -m pytest sjtu_tpmshx/tests/integration_tm1/test_three_process.py -q --timeout=900 --timeout-method=thread`

Result: **2 passed in 128.71 s, native exit 0**. Each dimension starts three
real processes. Preparation saves YAML/HDF5, its source directory is removed,
solve reads only the relocated Case, then Case files are removed before
postprocessing reads only results.h5. Each process checks forbidden imports.
Receiver TPMSHX_CHI_S=.99, SIMPLE_TOL=.9, CONV_MODE=legacy, VAR_RHOCP=0
cannot reinterpret the prepared physical/numerical settings.

Both archived results remain converged=True. Q/dP/Tout match the original
B20/B30 records at rtol=1e-10 and atol=1e-10, also matching the preceding
in-memory integration. 2D Q remains W/m and 3D Q W. The separate retained
mixed-fluid nonconvergence evidence is not superseded by these air baselines.

Local artifacts/logs are preserved under `.cache/tm1-io/B20-files` and
`.cache/tm1-io/B30-files`. They are generated numerical artifacts, not new raw
measurements, and are not committed. Remote CI and minimal-install execution
remain separate required checks.

## Broader regression record

The first fast-suite run exited 1: **15 failed, 2941 passed, 19 skipped,
77 deselected, 271 warnings in 521.09 s**. The original log remains at
`.cache/tm1-io/fast-suite.log`. Five warning-hook tests still patched the old
location after the shared model extraction; four source-inspection checks
still read the old pipeline location; one import-layer check exposed model
catalog validation in domain rather than I/O. These were corrected without
changing physical assertions. Targeted results: warning hooks 5 passed;
source/import boundaries 9 passed.

The remaining five failures compared the complete legacy info mapping against
an expected mapping without the newly captured native state. Their existing
EOS, cancellation, convergence and energy assertions remain intact; additional
assertions verify final native enthalpy, inlet enthalpy and zero face mass in
the controlled fixture. The whole true-h coupled-energy file passed 30 tests.
Combined file-I/O, architecture and true-h checks then passed **36 tests in
0.91 s, native exit 0**. Relative as well as absolute imports are checked.
These targeted repairs do not relabel the original full-suite run as green;
a fresh full CI run is still required.

The production `python -m sjtu_tpmshx.cli` now dispatches the same independent
file commands. Repeating the actual B20/B30 three-process test through this
public entry point passed **2 tests in 9.94 s, native exit 0** (warm JIT cache;
not a performance comparison). Existing legacy CLI status/dry-run tests passed
**11 tests in 0.08 s, native exit 0**. This proves the file-command route;
the old config-only CLI route still awaits the common application adapter.
