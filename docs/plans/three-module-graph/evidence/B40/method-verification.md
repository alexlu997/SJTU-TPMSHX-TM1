# Numerical-method evidence after historical attribution

2026-09-11, candidate `fa86a3d`. Existing tests were run in the fixed
73-package environment from the current worktree with local cache directories:

```
python -m pytest sjtu_tpmshx/tests/test_wall_momentum_flux.py \
  sjtu_tpmshx/tests/test_simple_wall_bc.py \
  sjtu_tpmshx/tests/test_wall_port_geometry.py \
  sjtu_tpmshx/tests/test_ltne_3d_end_cells.py -q
```

The actual command used `/private/tmp/sjtu-tm1-io-venv/bin/python` from
`.venv-path`. Result: **347 passed in 6.18 s, native exit 0**. Log:
`.cache/b40-method-verification.log`. No tests or thresholds were changed.

The wall suite verifies half-cell viscous conductance against the analytic
wall flux in 2D/3D, actual outlet-neighbour coupling, update/coefficient parity
on nonuniform grids, and retention of both z walls for one-layer 3D. Its
independent Brinkman square-duct sine-series comparison retains the original
coarse refinement failure as a reported observation and checks the two finer
orders against the existing >1.8 criterion plus finest relative error <0.005.
These provide numerical-method evidence for the reachable wall change; they
do not establish a whole-exchanger experimental error bound.

The end-cell suite verifies the actual full endpoint control-volume behavior.
Together with the historical six-face energy comparison, this supports the
discrete conservation rationale for replacing pinned/copied end layers. The
historical original-budget failures and the current engineering-budget
results remain separate artifacts.

The inherited README explicitly says affected production acceptance after
the wall change is pending (`docs/history/v2-readme.md`, wall-model section).
This run does not reverse that statement. Reference disposition still needs
an explicit decision; B40 stays failed, with no pin or tolerance change.
