"""Import-DAG locks (openspec arch-b-c-e batch B + contracts-layer).

The kernel import direction is:

    tpms_geometry ← tpms_props ← df_surrogate ← tpms_calc / simple_solver / ...

and pipelines must be importable without controllers (contracts-layer).
These tests run each probe in a FRESH interpreter so this test module's own
imports cannot pollute sys.modules.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PKG = str(Path(__file__).resolve().parents[1])


def _probe(code: str) -> None:
    r = subprocess.run([sys.executable, '-c', code], cwd=_PKG,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"probe failed:\n{r.stdout}\n{r.stderr}"


def test_df_surrogate_is_below_the_kernel():
    """df_surrogate must import via the tpms_props LEAF only — pulling
    tpms_calc/simple_solver back in would recreate the two-way coupling."""
    _probe(
        "import sys; import df_surrogate.predict; "
        "bad = [m for m in ('sjtu_tpmshx.models.tpms_calc', 'sjtu_tpmshx.solvers.simple_solver')"
        " if m in sys.modules]; "
        "assert not bad, f'df_surrogate pulled kernel modules: {bad}'; "
        "assert 'sjtu_tpmshx.models.tpms_props' not in sys.modules  # backend is lazy too"
    )


def test_tpms_props_is_a_leaf():
    """tpms_props must not import df_surrogate or the solvers above it."""
    _probe(
        "import sys; import sjtu_tpmshx.models.tpms_props; "
        "bad = [m for m in sys.modules if m.startswith('df_surrogate')"
        " or m in ('sjtu_tpmshx.models.tpms_calc', 'sjtu_tpmshx.solvers.simple_solver')]; "
        "assert not bad, f'tpms_props is not a leaf: {bad}'"
    )


def test_pipelines_import_without_controllers():
    """contracts-layer lock: stages modules must not pull controllers."""
    _probe(
        "import sys; import pipelines.stages_2d, pipelines.stages_3d; "
        "bad = [m for m in sys.modules if m.startswith('controllers')]; "
        "assert not bad, f'pipelines pulled controllers: {bad}'"
    )


def test_legacy_orchestration_does_not_modify_backend_namespace():
    _probe(
        "from sjtu_tpmshx.solvers.backends.python.three_d import runtime; "
        "before = dict(vars(runtime)); "
        "import sjtu_tpmshx.pipelines.run_stack_3d; "
        "assert vars(runtime).keys() == before.keys(); "
        "assert all(vars(runtime)[key] is value for key, value in before.items())"
    )
