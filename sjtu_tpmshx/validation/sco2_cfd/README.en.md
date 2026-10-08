<a id="sco2-cfd现行-nu-工具与历史-d-f-归档"></a>

# sCO2 CFD: current Nu tools and historical D-F archive

[中文](README.md) | [English](README.en.md)

Current data is under `data/raw_data/cfd/sco2/{Diamond,Gyroid}/`. The shared reader is `df_surrogate/load_sco2_cfd.py`. It keeps topology, layout, pressure/density, and raw-field guards.

`fit_nu_sco2.py` keeps Nu variant fits and leave-one-geometry/pressure-out validation. It writes `.cache/reports/sco2_cfd/nu_sco2_fit_coeffs.csv` and `nu_sco2_logo.csv`. Research refits do not automatically update current coefficients in `models/nu_correlations.py`.

Previous `compare_smooth_df.py`, `make_error_report.py`, and SmoothDF/sCO2 B/m models retired with the previous D-F route. The original README's 2026-07-15 coefficients, applicability, failure bands, and restart list stay in the [fixed historical version](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_cfd/README.md). Those are historical results, not new acceptance of the current production model.

Current resistance uses joint water+sCO2 geometry-fixed K/cF and reviewed experimental corrections. See [architecture](../../../docs/architecture.md). The [historical model index](../../../docs/history/legacy-models.md) gives complete previous entries. Current experimental sCO2 mode reads total effective Nu coefficients from `configs/sco2_effective_nu.json`. Select them explicitly with `models.nu_correlations.sco2_effective_nu_config()`. See [model resources](../../../docs/model-resources.en.md#sco2-有效-nu-系数) for usage, calibration provenance, and limited validation scope.

Previous `fit_nu_correction` and `nu_bytemp_report` retired with the experimental anchored-gamma route. Their [fixed source](../../../docs/history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20) cannot reconstruct current coefficients. Kept CFD base-correlation fitting, reading, and cleaning are unaffected.
