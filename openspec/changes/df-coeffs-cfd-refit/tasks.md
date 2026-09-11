## Status (2026-06-30)

**Phase 1–2 + a gate-safe backend DELIVERED.** Raw water CFD (40 geom) re-extracted via 2-stage decoupled fit → K/Dh² scatter 24.7×→1.3–1.6×; log-space TPS/GP surfaces interpolate at **cF LOO 5.1 %(G)/14.5 %(D), K LOO 6.2 %(G)/19.7 %(D), end-to-end Δp LOO 13.0 %(G)/20.3 %(D)** — **~6× better than gamma_df** (87/122 %). Figure: [df-refit-loo 历史图](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/assets/df-refit-loo.png). Root cause confirmed: col47 anchors anomalous (L4 t-trend reversed, L6 3–4× spike).

**DEPLOYED into the production default `gamma_df`** (2026-06-30 #2, user-directed): the clean CFD **K**-surface replaced the SmoothDF D_h² K trend inside `GammaDF` (c_F unchanged). The transient `cfd_refit` backend was folded in and removed. **Shanghai 3D dP 5.05→5.28 % / Q 3.20→3.21 %** (re-baselined: golden-point K values, projector baseline JSON, evaluator frozen tuples, shanghai regression pin), water-Δp Diamond 0.33→0.40 / Gyroid 0.62→0.68. Full pytest green.

**Air↔water cross-check DONE (was already run 2026-06-11, re-verified 2026-07-01).** Two INDEPENDENT smooth CFD (dedicated air CFD `data/raw_data/air-cfd-raw.xlsx` ≈ `server-pyfluent/Data_All_1,0.xlsx`, 840 pts, 20 geom + water CFD), same DF fit, cF compared over 20 overlapping geoms: **cF(air)/cF(water) median 0.96** (report's 0.98 reproduced; Gyroid + Diamond L4–L6 = 0.78–1.18). → **(K, c_F) geometric / fluid-independent, self-data proof** (method-section grade). Diamond L7/L8 = 1.3–2.4× is a two-CFD mesh/geometry-generation systematic (NOT fluid), i.e. a ~2× uncertainty band in the smooth baseline for Diamond large cells. K is NOT cross-checkable from air (Re≥500 above the Darcy knee — scatter 0.18–3.65×). Shanghai G7/0.6: cF_air 157 / cF_water 138, both ~3.5× below the experiment-needed 535 → 2nd fluid confirms the gap is ROUGHNESS. Figure [df-air-water-cf 历史图](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/assets/df-air-water-cf.png). Full report: `vault/reports/method/2026-06-11-df-water-cfd-c6-trust-hybrid-CN.html`.

**Deferred:** full **c_F** surface deployment (needs roughness γ — blocked on experiment convention, [[d76-cannot-calibrate-nu]]); production default switch (user decision). The full smooth-cF surface is validated but Shanghai needs the gate-calibrated c_F (registration contract — see plhub_gp precedent).

---

## 1. Extraction — per-geometry (K, c_F) in one convention

- [ ] 1.1 Reduce raw **water** CFD (40 geom) via `(Δp/L)/u = μ/K + ρ·c_F·u` with normalized u + NNLS; per geometry record K, c_F, R², n, ε_A, D_h, Re-range
- [ ] 1.2 Compute per-geometry **Forchheimer-number coverage** (Fo at Re_min/Re_max); flag geometries where K (Fo never ≪0.1) or c_F (Fo never ≫1) is not identifiable
- [x] 1.3 Reduce raw **air** CFD — DONE. Source is the dedicated `data/raw_data/air-cfd-raw.xlsx` (`All_Cases_Combined`, 20 geom, Re 500–20000, `dP_core_Pa` + `L_core_report_mm`, interstitial `v_ref_excel_m_s`, SAME 3-cell core convention as water-cfd-raw). NOT the `试验记录表` col35 (operating-point-matched, convention-broken — gives garbage). See [[air-cfd-crosscheck]]
- [x] 1.4 **Air↔water cross-check** — DONE. cF(air)/cF(water) median **0.96** over 20 geoms (Gyroid + Diamond L4–L6 within ±20%); (K,c_F) geometric confirmed. Diamond L7/L8 1.3–2.4× = two-CFD systematic (mesh/geom, not fluid). Decision: **water-only for the smooth surface** (water spans Re 100–50k incl. Darcy; air can't see K); air is the independent check confirming fluid-independence, not pooled into the fit
- [ ] 1.5 Write extracted table to `df_surrogate/_prebuilt/df_cfd_coeffs.csv` (tp, L, t, eps_A, Dh, K, cF, R2, Fo_lo, Fo_hi)

## 2. High-accuracy interpolation surface (the target)

- [ ] 2.1 Build LOO harness: leave-one-geometry-out over the 5×4 grid per topology, RMSRE on c_F and K
- [ ] 2.2 Fit **log c_F** vs (log L, log t) per topology: anisotropic Matérn-5/2 GP **and** TPS; pick lower LOO. Also try ε-primary basis; keep winner
- [ ] 2.3 Fit **log K**: GP/TPS in log space + physical prior `K≈C·L²·(a+b·ε)`; regularize/shrink where Fo flags K unidentifiable
- [ ] 2.4 Report LOO RMSRE (c_F, K) — **gate: c_F LOO ≪ gamma_df 2.5/2.6%** over all 40 geom; figure cF/K vs L per t (anchors + surface + LOO points)

## 3. Roughness factor (multi-fidelity, multiplicative)

> **(K, c_F) are GEOMETRIC — one set per geometry, never fluid-specific.** γ is a
> geometric roughness factor (a `γ(Re)` at most), shared by air AND water; do NOT
> fit a separate `γ_water`. See design D6 PHYSICS CONSTRAINT (2026-07-01).

- [ ] 3.1 Reconcile experiment Δp convention (core vs total/manifold, channel N) for `D_7_6` air + `7-6-Water` G/D FIRST — this likely removes most of the water gap (artifact, not physics). Resolve or document (see [[d76-cannot-calibrate-nu]])
- [ ] 3.2 If a residual air↔water discrepancy survives the convention fix, model it as ONE geometric `c_F(Re)` (or `γ(Re)`) fit from **pooled air+water** — air pins high-Re, water pins low-Re. NO fluid-specific γ; NO second roughness factor; NO additive KOH
- [ ] 3.3 Validate the single geometric closure against BOTH experiments end-to-end (water 7-6, air D_7_6); the same (K, c_F[(Re)]) must fit both — report residual

## 4. Backend integration + gates

- [ ] 4.1 New backend module (`df_surrogate/cfd_refit.py`) reading the prebuilt table + surface; `predict(L,t,eps)->(K,cF)`; register alongside gamma_df/rbf (`backend.py`)
- [ ] 4.2 End-to-end **water Δp RMSRE** on `7-6-Water-dp` with the new backend — must beat gamma_df 0.33/0.63×
- [ ] 4.3 **Shanghai 3D headline** (`validate_shanghai_3d_real`) with the new backend — must not regress the README Δp/Q (hard invariant; default NOT switched until this passes)
- [ ] 4.4 Full pytest green; new backend has unit + LOO regression tests; golden gates bit-identical (default unchanged)

## 5. Deliverable

- [ ] 5.1 Summary: LOO accuracy table (c_F, K) over the whole dataset, water-Δp improvement, the col47-anomaly root cause; figure(s) for README closure section (replace/augment the gamma_df cF interpolation figure)
- [ ] 5.2 Decide (with user) whether to switch the production default to the new backend

---

## Status addendum (2026-07-22, 升级循环 candidate-D · D-2a, iter 66)

**入口段污染发现（iter 65-66）改变本变更的提取基**：dp_core 是含入口周期的
3 段整核压降；p0..p3 逐段实测显示整核/发展段(2+3) 压降比 = Diamond 1.015 /
**Gyroid 1.155**（且随 Re 升到 1.5——Forchheimer 支配）。真实 HX ~26 胞元
入口占比 ~4% ⇒ 均质化闭合应取**周期发展值**。sCO2 数据集（同一后处理管线）
同构确认（G 整核 f/发展 = 1.168）。

**发展段重提取已交付**（`validation/df_refit/extract_dev_coeffs.py`，两段法
字面实现 + 阈值自校准 Re_hi≥12800/Re_lo≤400，core 复现对生产表 med 0.98 紧）：

| 量 | Diamond dev/core | Gyroid dev/core |
|---|---|---|
| cF | 0.949 (−5%) | **0.831 (−17%)** |
| K  | **0.846 (−15%)** | 0.950 (−5%) |

候选表 `_prebuilt/df_cfd_coeffs_dev.csv`（生产表未动）；对比表
`reports/df_refit/dev_vs_core_vs_smoothdf.csv`（含 SmoothDF(Re_ref)/cF_dev
= ×1.53 两拓扑一致的绝对水平差）。**含义：2026-06-30 已入产线的 K 面按发展
段口径应下修 D −15%/G −5%（水侧 Δp 波及，air 窗 Darcy 份额 1-6% 上海几乎
不动）——归 D-3 换默认重基准一并裁**；本变更 2.x（LOO 面）与 4.x（backend）
的后续实施应以 dev 表为基。
