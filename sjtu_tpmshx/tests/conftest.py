"""Pytest fixtures and child-process source-root bootstrap.

The shared worktree venv intentionally has no editable project install. Some
tests start fresh Python processes from the package directory or a temporary
script directory, where the repository root is not on ``sys.path``. Export the
current checkout root through ``PYTHONPATH`` so those children import
``sjtu_tpmshx`` from the same worktree as pytest.

2026-05-09 Phase Qt-headless fix: also forces ``QT_QPA_PLATFORM=offscreen``
*before* any test module imports PySide6. Without this, full-suite runs
on Windows would crash with exit code 9 once the first test instantiated
QApplication on the default 'windows' platform plugin (no display avail).
The individual Qt test files set this same env var via
``os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')``, but `setdefault`
is a no-op when Qt has already been initialised by a prior import in the
same process. Setting it here at conftest load time guarantees it lands
before any PySide6 module is imported.
"""
import os
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_INHERITED_PYTHONPATH = os.environ.get('PYTHONPATH')
os.environ['PYTHONPATH'] = os.pathsep.join(
    part for part in (_REPO_ROOT, _INHERITED_PYTHONPATH) if part)

# Must run BEFORE any PySide6 import — pytest loads conftest.py at session
# start, before collecting tests, so this env var is in place for every
# subsequent test_*.py import.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import sjtu_tpmshx  # noqa: F401 — verify the current checkout is importable


# 2026-05-09 — Eagerly instantiate a process-wide QApplication so that:
#   1. The first Qt-touching test doesn't pay the platform-plugin
#      bootstrap cost mid-test (improves CI determinism).
#   2. A prior test that calls QCoreApplication([]) (e.g.
#      test_compute_orchestrator) cannot leave an incompatible application
#      instance that blocks the next test from creating a real QApplication.
#   3. The 'offscreen' platform is locked in BEFORE any test_*.py decides
#      whether to call QApplication([]) — guarantees no GUI window pops.
# Skipped silently when PySide6 is unavailable (rare; sentinel CI envs).
try:
    from PySide6.QtWidgets import QApplication as _QApp
    if _QApp.instance() is None:
        # The argv list intentionally includes the offscreen flag so the
        # platform plugin selection is unambiguous even if a sub-test
        # fiddles with os.environ later in the session.
        _QApp(['pytest', '-platform', 'offscreen'])
except Exception:
    pass


# ── fast-tier heavy marking (P3.1, 2026-07-20) ──────────────────────────────
# Duration-based, manifest-driven: _fast_tier_manifest.txt lists node-ids
# measured >= 30s in the durations census (regen via
# runs/tools/build_fast_tier_manifest.py). They get the `heavy` marker at
# collection time — zero test-file churn, and scripts/run_tests_fast.ps1
# excludes them with -m "not heavy". The FULL suite still runs them; the
# fast tier is dev feedback, NOT the verification gate. Distinct from the
# `slow` marker (CI skip-list — semantic, hand-curated; v1 lesson: do not
# conflate) and the legacy `fast` marker (opt-in smoke subset).
_FAST_TIER_MANIFEST = Path(__file__).with_name('_fast_tier_manifest.txt')


def _heavy_norm(nodeid: str) -> str:
    """Invocation-dir-independent node-id key: file BASENAME + test part.

    Node-ids differ by prefix depending on the pytest invocation cwd
    (``sjtu_tpmshx/tests/test_x.py::t`` from repo root vs ``tests/...``
    from the package dir); test file basenames are unique across the
    suite (flat dir + design/), so the basename suffix is a stable key.
    """
    file_part, sep, rest = nodeid.replace('\\', '/').partition('::')
    return file_part.rsplit('/', 1)[-1] + sep + rest


def pytest_collection_modifyitems(config, items):
    try:
        raw = _FAST_TIER_MANIFEST.read_text(encoding='utf-8').splitlines()
    except OSError:
        return
    heavy = {_heavy_norm(ln.strip()) for ln in raw
             if ln.strip() and not ln.lstrip().startswith('#')}
    if not heavy:
        return
    import pytest as _pytest
    for item in items:
        if _heavy_norm(item.nodeid) in heavy:
            item.add_marker(_pytest.mark.heavy)
