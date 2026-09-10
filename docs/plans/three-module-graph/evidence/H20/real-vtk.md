# Real native VTK handoff

Source base 3f5c519, same configured 73-package locked environment. Existing
real full 2D and 3D public application tests now extend their independent
HDF5 postprocess process: export results.vtk, read it with VTK's rectilinear
grid reader, assert cell count and exact F-order values for every native field.
The same process continues to reject solver/preprocess/pipeline/Numba/Qt imports.
No exporter or numerical implementation changed.

Command: `python -m pytest sjtu_tpmshx/tests/integration_tm1/test_public_api.py
-q --timeout=600 --timeout-method=thread`, with worktree-local caches and
OPENBLAS/OMP/NUMBA_NUM_THREADS=1.

- First attempt: 2 failed, native exit 1 (`.cache/p40/real-vtk.log`). The VTK
  reader defaults to the first scalar; subsequent arrays were absent in its
  output. No file/data correction was needed.
- After `ReadAllScalarsOn()`: 2 passed in 10.41 s, native exit 0
  (`.cache/p40/real-vtk-final.log`). All original source/application comparisons
  remain in the tests. Ruff and diff checks passed.

This complements the earlier synthetic field/metadata VTK check. It is real
numerical-file interoperability evidence, not new physical accuracy evidence.
Remote CI and final independent review remain outstanding.
