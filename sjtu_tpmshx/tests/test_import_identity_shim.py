"""P1.8b F2 — the import-identity shim is RETIRED (openspec
p18b-import-style-migration).

W0 installed a transitional meta-path finder in ``sjtu_tpmshx/__init__``
aliasing top-level and package-qualified imports to one module object; waves
W1–F1 migrated every caller and library internal to the package style; F2
removed the shim. These tests pin the END state:

- the package init is side-effect-free (no finder, no sys.path insert);
- the package style is the ONLY convention (module identity, logger naming);
- the legacy top-level style is dead in a clean interpreter.

If someone re-introduces a bootstrap or finder, or a module regrows a
top-level import, these assertions are the tripwire. History: see the
openspec change's tasks.md and the retired upgrade records in Git history.
"""
import subprocess
import sys


def test_package_init_is_side_effect_free():
    """The package init must be a docstring and NOTHING else — no finder,
    no sys.path insert, no imports (AST-level: a raw-source grep would
    false-positive on the docstring narrating the shim's history)."""
    import ast
    import sjtu_tpmshx
    tree = ast.parse(open(sjtu_tpmshx.__file__, encoding='utf-8').read())
    non_doc = [n for n in tree.body
               if not (isinstance(n, ast.Expr)
                       and isinstance(n.value, ast.Constant)
                       and isinstance(n.value.value, str))]
    assert not non_doc, (
        "sjtu_tpmshx/__init__.py grew executable statements — F2 retired "
        f"the shim; found: {[type(n).__name__ for n in non_doc]}")
    finders = [f for f in sys.meta_path
               if getattr(type(f), '_P18B_IDENTITY_FINDER', False)]
    assert not finders, "identity finder still installed at runtime"


def test_legacy_toplevel_style_is_dead_in_clean_interpreter():
    """`import solvers` must fail in a fresh interpreter (repo-root cwd,
    which puts the REPO ROOT — not the package dir — on sys.path)."""
    r = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.pop(0) if sys.path and not sys.path[0] '
         'else None\n'
         'try:\n'
         '    import solvers\n'
         'except ModuleNotFoundError:\n'
         '    raise SystemExit(0)\n'
         'raise SystemExit(1)'],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (
        "top-level `import solvers` still resolves in a clean interpreter — "
        "some bootstrap survives:\n" + r.stderr[-500:])


def test_package_style_resolves_and_is_canonical():
    import sjtu_tpmshx.solvers.nu_correlations as nc
    from sjtu_tpmshx.models import nu_correlations
    assert nc is nu_correlations
    assert nc.__name__ == 'sjtu_tpmshx.models.nu_correlations'
    import sjtu_tpmshx.solvers as s
    assert s.__name__ == 'sjtu_tpmshx.solvers'


def test_logger_taxonomy_is_packaging_neutral():
    """get_logger strips the package prefix: logger names stay
    tpmshx.<subsystem> exactly as before the migration (F2 decision —
    the logging taxonomy must not encode packaging history)."""
    from sjtu_tpmshx.logutil import get_logger
    lg = get_logger('sjtu_tpmshx.solvers.threads')
    assert lg.name == 'tpmshx.solvers.threads'
    lg2 = get_logger('solvers.threads')
    assert lg2.name == 'tpmshx.solvers.threads'
    assert lg is lg2
