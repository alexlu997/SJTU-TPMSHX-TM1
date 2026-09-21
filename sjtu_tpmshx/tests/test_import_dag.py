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

_REPO = str(Path(__file__).resolve().parents[2])


def _probe(code: str) -> None:
    r = subprocess.run([sys.executable, '-c', code], cwd=_REPO,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"probe failed:\n{r.stdout}\n{r.stderr}"


def test_df_surrogate_is_below_the_kernel():
    """df_surrogate must import via the tpms_props LEAF only — pulling
    tpms_calc/simple_solver back in would recreate the two-way coupling."""
    _probe(
        "import sys; import sjtu_tpmshx.df_surrogate.predict; "
        "bad = [m for m in ('sjtu_tpmshx.models.tpms_calc', 'sjtu_tpmshx.solvers.simple_solver')"
        " if m in sys.modules]; "
        "assert not bad, f'df_surrogate pulled kernel modules: {bad}'; "
        "assert 'sjtu_tpmshx.models.tpms_props' not in sys.modules  # backend is lazy too"
    )


def test_tpms_props_is_a_leaf():
    """Property imports may reach training-domain constants, not inference/solvers."""
    _probe(
        "import sys; import sjtu_tpmshx.models.tpms_props; "
        "allowed = {'sjtu_tpmshx.df_surrogate', 'sjtu_tpmshx.df_surrogate._domain'}; "
        "bad = [m for m in sys.modules if (m.startswith('sjtu_tpmshx.df_surrogate')"
        " and m not in allowed) or m.startswith('sjtu_tpmshx.solvers')"
        " or m == 'sjtu_tpmshx.models.tpms_calc']; "
        "assert not bad, f'tpms_props is not a leaf: {bad}'"
    )


def test_pipelines_import_without_controllers():
    """Scripted orchestration and input preparation stay below controllers."""
    _probe(
        "import sys; import sjtu_tpmshx.pipelines.run_stack_3d; "
        "import sjtu_tpmshx.preprocess.two_d.preparation; "
        "import sjtu_tpmshx.preprocess.three_d.preparation; "
        "bad = [m for m in sys.modules if m == 'controllers' "
        "or m.startswith(('controllers.', 'sjtu_tpmshx.controllers'))]; "
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
