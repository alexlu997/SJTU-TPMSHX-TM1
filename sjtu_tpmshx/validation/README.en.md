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
  MMS/GCI tables, the Shanghai main benchmark and active tests stay.
  See the [retirement index](../../docs/history/retired-tools.md) for retired diagnostic tables.

Keep the original members, thresholds and failures. Import success, convergence, conservation and experimental accuracy are separate conclusions.

Python MMS A3/A4/B4 commands are retired in 0.2. Their [original entry points](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/v0.1.0/sjtu_tpmshx/validation/cases) retain the historical interface. Current [native MMS tests](../tests/native/test_temperature_mms.py) check manufactured fields, convergence on each grid, finite errors, spatial order and physical inlet response. The applicable thresholds stay.

Tests that read frozen repository CSVs validate historical evidence. They do not show that the current code completed a new numerical sweep.

The original 2026-05 index stays in [fixed history](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/sjtu_tpmshx/validation/README.md).
