<a id="验证工具"></a>

# Validation tools

[中文](README.md) | [English](README.en.md)

The [tool index](../../docs/tools.en.md) lists current entries, data requirements and commands.
Run modules from the repository root with the interpreter recorded in `.venv-path`.
Local data is in `data/raw_data/`.

- [cases](cases/) contains Nu, heat exchanger and conservation checks.
- [hx_experiments.py](hx_experiments.py) gives shared reading for current experiment tools.
- [df_refit](df_refit/), [sco2_cfd](sco2_cfd/) and [sco2_exp](sco2_exp/) contain current closure checks and explicit offline fitting.
- [cf_aniso](cf_aniso/README.en.md) contains a research request and fitting template. Direction-resolved CFD data and calibration stay unavailable.
- The [original CSV status record](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5c517b415be0adbfc7bbfd205a3dba07fe8792a8/sjtu_tpmshx/validation/_CSV_STATUS.md) keeps historical values and their version context.
  GCI tables, the Shanghai main benchmark and active tests stay.
  See the [retirement index](../../docs/history/retired-tools.md) for retired diagnostic tables.

Keep the original members, thresholds and failures. Import success, convergence, conservation and experimental accuracy are separate conclusions.

Python MMS A3/A4/B4 commands are retired in 0.2. Their [original entry points](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/v0.1.0/sjtu_tpmshx/validation/cases) retain the historical interface.
Current [native MMS tests](../tests/native/test_temperature_mms.py) execute the C++ kernel.
They check manufactured fields, convergence on each grid, finite errors and the limits below.
The labels `1d/2d/3d` describe field variation within the 3D kernel. They do not select different backends.

| Check | Retained limits |
| --- | --- |
| A3: nonconservative scheme, 1d/2d/3d fields | A/B/solid L2 orders ≥ 1.5/1.5/1.8; each phase R² ≥ 0.999; each phase relative L2 < 1% on grid 30 |
| A4: nonconservative scheme, 3d regions | Both outlet orders ≥ 0.8; lateral solid order ≥ 1.5; each interior order ≥ 1.8 and finest-grid relative L2 < 1% |
| Current physical inlet face: both schemes, 1d/2d/3d fields | Normalized difference between one kernel sweep and an independent finite-volume response < 1e-12; adjacent cell temperatures stay unknowns |
| B4: conservative scheme, 3d field | Each phase L2 order ≥ 1.8 and R² ≥ 0.99 |

Each refinement group also requires each phase relative L2 < 1% on its finest grid.
Grid-20 field checks retain relative L2 < 2% and Linf < 3 K.
The three tests that read frozen MMS CSVs and their exclusive data have [fixed historical entries](../../docs/history/README.en.md#mms-reference-retirement).
The former A4 pinned-cell criterion keeps its historical meaning. The current physical-face inlet check stays unchanged.

The original 2026-05 index stays in [fixed history](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/validation/README.md).
