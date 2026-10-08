<a id="历史资料索引"></a>

# Historical material index

[中文](README.md) | [English](README.en.md)

See [architecture](../architecture.md) and the [project README](../../README.en.md) for current structure and operation.

Previous manuals, development logs, V2 README files, completed projects, and fixed experiments have left the current tree. The [retired tool index](retired-tools.md) links original files at fixed commits. The [retired model index](legacy-models.md) covers previous γ/RBF, SmoothDF, and related reports. The sCO2 Nu anchored-gamma route, fitting tools, and temperature reports retired on 2026-09-20 stay at [fixed source entries](legacy-models.md#sco2-nu-旧锚定路线2026-09-20). See [model resources](../model-resources.en.md#sco2-有效-nu-系数) for current total effective coefficients and applicability.

The [document archive index](retired-tools.md#旧规范与状态原稿归档2026-09-13) also tracks previous OpenSpec split plans and CSV status drafts. Current supplementary specifications stay under `openspec/specs/`. The word “current” in historical drafts does not describe this version.

<a id="通过固定提交查阅的历史产物"></a>

## Historical artifacts at fixed commits

These artifacts have left the current tree. Original text and values stay in merged commit [d3ba040](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/d3ba040de0d43fce8e9b485396a5b660c2d87c5f).

| Material | Historical entry | File count |
| --- | --- | ---: |
| Previous README/report images | [assets](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/assets) | 8 |
| Optimization outputs from 2026-05-13 | [qnehvi_3d_20260513_175108](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/opt_runs/qnehvi_3d_20260513_175108) | 7 |
| Unadopted model exploration from 2026-04 | [Scratch conclusions and failures](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/reports/scratch/README.md) | 6 |
| Architecture/handoff snapshot from 2026-07 | [Atlas index](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/README.md) | 19 |

Exploratory failures and rejected candidates keep their original conclusions. They do not show new acceptance of current models. Current runtime resources and effective tests stay in the source tree. The next section keeps frozen snapshots, formal failures, and Graph acceptance records.

<a id="2026-09-18-历史材料整理"></a>

## Historical material reorganization, 2026-09-18

These originals have left the current tree. Their text and values stay in merged commit [5534369](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/5534369de8f1f9e535076b36b55d2bce2c1d1e38). Local copies also stay. New research work and outputs stay only in local `.cache/`. Historical links do not require current code to rerun retired commands or rewrite Git history.

| Historical material | Fixed entry | Current use or replacement |
| --- | --- | --- |
| Three-module requirements, task graph, 45 states, and evidence | [three-module-graph](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/plans/three-module-graph), 176 files | [Capabilities](../capabilities.en.md) keeps 7 planned nodes, blocked Z10, and release conditions. Full requirements stay in history. |
| Eight dated reports and three stage plans | [Reports](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs), [plans](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/plans) | Historical maintenance, accuracy/performance, architecture, Nu speed, pressure-boundary, air–water convergence, and resistance-calibration records. Current rules are in architecture and model resources. |
| Fit tables and original navigation | [reports](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/reports), 7 CSV files plus README | Historical Nu/DF outputs. Review tools now write to `.cache/reports/`. Production coefficient resources stay. |
| 3D golden and metadata | [golden_3d.json](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/golden_3d.json), [metadata](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/golden_3d.meta.json) | Environment-specific 2026-07 snapshot, not current CI or experimental accuracy baseline. |
| Manual 2D/3D golden capture scripts | [Original _out](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/runs/_out), 2 scripts | Effective 2D test settings moved into tests. 3D settings were already in tests/cases_3d.py. |
| Previous gamma projection snapshot | [Original JSON](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/tests/_data_df_projection_baseline.json) | Current projection tests use analytically defined synthetic coefficients, without previous model data. |
| Partial-B retrospective audit, 2026-05-04 | [Original script](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/validation/cases/audit_partial_b_ltne.py) | Closed one-time diagnosis. Current conservation checks and solver evidence fields stay. |
| External AI workflow templates | [agents](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/agents), 3 files | Not part of runtime, CI, or current project rules. |

Original B40 failures, unadopted candidates, frozen values, and states stay unchanged. M-A completion and later repairs do not turn historical failures into passes. M-B still needs separate implementation and acceptance. Current calibration formulas, data columns, and ranges are in [model resources](../model-resources.en.md). Dated reports no longer determine current parameters.

<a id="2026-09-29-求解器软件参考修订"></a>

## Solver software reference revision, 2026-09-29

Nonuniform grids now reconstruct heat flux with actual half-cell thermal resistance and physical distance. Momentum uses shared viscous and continuity mass fluxes. Richardson refinement bisects actual cells. Software references for Q, pressure drops, and outlet temperatures changed with this discretization repair. Configurations, iteration budgets, convergence gates, and comparison tolerances stayed unchanged. Experimental data, model coefficients, and experimental accuracy gates were not revised.

Complete earlier values and tests stay at [66f523b](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/66f523b5157672079923bfbdc997873a2369cda8).

| Software reference | Original entry | Kept verification meaning |
| --- | --- | --- |
| B20 2D air and two mixed-fluid cases | [test_2d_real.py](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/66f523b5157672079923bfbdc997873a2369cda8/sjtu_tpmshx/tests/integration_tm1/test_2d_real.py) | Backend Richardson Q and public native Q stay separate. Both short-budget mixed-fluid cases must still return nonconverged. |
| Uniform/nonuniform 2D/3D screening | [test_evaluator_frozen_values.py](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/66f523b5157672079923bfbdc997873a2369cda8/sjtu_tpmshx/tests/test_evaluator_frozen_values.py) | Independent Q/pressure recalculation. Mass stays bit-identical. One-density-pass 2D screening is not full coupling validation. |
| Public 3D air and file/GUI interfaces | [test_three_process.py](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/66f523b5157672079923bfbdc997873a2369cda8/sjtu_tpmshx/tests/integration_tm1/test_three_process.py), [test_public_gui.py](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/66f523b5157672079923bfbdc997873a2369cda8/sjtu_tpmshx/tests/integration_tm1/test_public_gui.py) | Three processes and GUI share public metric definitions. Save/reload keeps states and values. |

These are software behavior references. Numerical reproduction, conservation/grid qualification, and experimental errors require separate verification.

<a id="2026-10-02-二维单侧导热与收敛参考修订"></a>

## 2D side-conductivity and convergence reference revision, 2026-10-02

Full 2D air/water model-h now defines each fluid's effective conductivity as its side porosity times conductivity. Thermal iterations must pass local discrete-equation checks. Existing Anderson acceleration completes them within the original budget. Stable outer-field changes cannot replace inner thermal convergence. B20 air references changed accordingly.

Configuration, budget, and `rtol=1e-10` stay unchanged. Previous references stay in [a0131ab tests](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a0131ab2e5e11b701711b75859c65ef80f7e6344/sjtu_tpmshx/tests/integration_tm1/test_2d_real.py).

| Software metric | Previous | Revised |
| --- | ---: | ---: |
| Native Q (W/m) | 31130.94175144736 | 31131.515711397526 |
| Richardson Q (W/m) | 31156.7524902476 | 31152.0469411321 |
| Public face dP A/B (Pa) | 1626.1295067141764 / 1188.8348821008549 | 1626.028297634257 / 1188.8113859451987 |
| Outlet T A/B (K) | 303.281741994655 / 334.7957041980853 | 303.2761483302114 / 334.7899628549054 |

This revision changes neither raw experimental data nor frozen coefficients in saved CaseData. Rebuilt CaseData uses the corrected preparation formulas. Software reference updates do not show independent experimental accuracy.

The same revision changed the 2D incompressible pressure reference. It moved from inlet-cell/profile weighting to physical inlet-face/geometric-opening-area averaging. Three-step short-budget sCO₂–water Q changed from 45624.58456665004 to 45624.58629116599 W/m. Air–sCO₂ Q changed from 4416.181405481553 to 4416.181525306756 W/m. Both cases must stay nonconverged.

They keep differences between final thermal inputs and final flow fields. These values are not convergence or physical-accuracy certificates.