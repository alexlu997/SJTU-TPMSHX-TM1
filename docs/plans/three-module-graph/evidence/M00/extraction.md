# Shared model extraction — partial M00/I55

Base: local G10 repair `4e272b7`; branch `codex/tm1/m00-repair`.
Formula source: TM1 main `c7f0138`, inherited numerical baseline `5f1cafb`.
No raw data, model coefficients, applicability ranges or acceptance thresholds
were changed. Resource versions are listed in `models/catalog.py`; they identify
the existing formulas and fixed CFD table, not Q accuracy acceptance.

Environment: `/Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python`.
`check_locked_environment`: 71 active packages match; `pip check`: pass.
All pytest runs below used worktree-local `.cache` for MPLCONFIGDIR and
XDG_CACHE_HOME, from this worktree root, with the absolute interpreter above.

Commands after `python -m pytest -q`:

- `sjtu_tpmshx/tests/test_tpms_calc.py sjtu_tpmshx/tests/test_fluid_props.py sjtu_tpmshx/tests/test_nu_correlations.py sjtu_tpmshx/tests/test_grid_schema.py sjtu_tpmshx/tests/test_continuous_field.py sjtu_tpmshx/tests/test_import_identity_shim.py sjtu_tpmshx/tests/test_import_layering.py`: first run 93 passed / 1 failed, native exit 1. Failure fixed the old module-name assertion to assert shared identity under the new physical-model owner; no numerical threshold changed.
- The same selection plus `sjtu_tpmshx/tests/models_tm1`: 95 passed, native exit 0, 2.53 seconds (before adding catalog test).
- `sjtu_tpmshx/tests/test_df_backend_registry.py sjtu_tpmshx/tests/test_predict_K_cF_vec_batch.py sjtu_tpmshx/tests/test_sco2_phase_a.py sjtu_tpmshx/tests/test_chi_s_homogenization.py sjtu_tpmshx/tests/test_pipeline_reexports.py`: 64 passed, 4 preserved applicability warnings, native exit 0, 84.96 seconds.
- `sjtu_tpmshx/tests/models_tm1 sjtu_tpmshx/tests/test_import_layering.py`: 3 passed, native exit 0, 2.13 seconds. Includes clean-process scalar/vector air/water/sCO2 evaluation and fixed CFD resource resolution without solver, pipeline, Numba or Qt imports; existing module aliases share identity.

No remote CI or independent review yet. No true module integration or M-A
acceptance follows from these results. Remaining M00 work includes complete
run-owned model declarations for all prepared modes and integration evidence.
