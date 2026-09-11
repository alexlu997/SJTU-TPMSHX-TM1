# P40 offline preparation evidence

Base: 2bf2bb2791a3ac2dce869083d9ae2e0c46468e5b; isolated
`codex/tm1/p40-offline-repair`. Independent review, CI and merge remain pending.
Environment: configured `/private/tmp/sjtu-tm1-io-venv/bin/python`, exact 73-entry
lock matched and pip check passed. Worktree-local Matplotlib/XDG caches.

L1/L2: `python -m pytest sjtu_tpmshx/tests/preprocess/test_offline_tm1.py
sjtu_tpmshx/tests/test_cache_and_source_guards.py
sjtu_tpmshx/tests/test_load_data_no_shanghai.py
sjtu_tpmshx/tests/test_import_layering.py -q`.
Final: 15 passed, 7 skipped in 2.30 s, native exit 0
(`.cache/p40/offline-final.log`). Earlier 14 passed/7 skipped and initial
3 passed runs also exited 0. Artificial inputs verify cleaning, known fitted
coefficients, CSV reload equivalence, non-overwrite, missing input/revision,
actual-path leakage guard, water raw-field retention and suspect flags,
existing Nu fit delegation, and ordinary full preparation with fitting blocked.
The skipped existing tests require a worktree-local raw workbook; they do not
represent passing raw-data tests. Ruff and diff checks passed.

Real local source: `/Users/luwenhuan/Documents/ChatGPT/SJTU-TPMSHX-data/raw_data`,
data revision ddf11acdf6c05340fb832e427d3861d0534bd934, selected files clean.
Explicit offline functions completed with native exit 0 (`real-offline.log`):

- Experiment cleaning: 328 rows; existing filter removed 18 low-Re L8 rows per
  topology. Both original filters and col47 pressure convention retained.
- Original SurrogateV3 col43/alpha fit: 12 derived geometries per topology,
  written only under `.cache/p40/real-publication/` with a source manifest.
- sCO2 Diamond: 5399 core rows and 10798 retained period-2/3 rows.
- sCO2 Gyroid: 5400 core rows and 10800 retained period-2/3 rows.
- Both sCO2 loaders passed the existing density/pressure check on 27 states;
  pressures remain the source campaign's 8/10/12/15 MPa. This is data-reduction
  evidence, not blanket production Nu applicability or experimental Q acceptance.

No PDE, source-data modification, production-table update, or external model
publication occurred. Current water CFD workbook is unavailable; synthetic
water I/O passed, real water reduction remains not run. The remaining quick
mode inlet-pressure preparation boundary is tracked in the offline decision.
