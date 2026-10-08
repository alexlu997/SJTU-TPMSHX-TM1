<a id="模型资源离线拟合与标定来源"></a>

# Model resources, offline fitting, and calibration provenance

[中文](model-resources.md) | [English](model-resources.en.md)

<a id="离线数据与正式准备流程"></a>

## Offline data and formal preparation

`sjtu_tpmshx.preprocess.offline` exposes experiment, water CFD, sCO2 core, and sCO2 segment cleaners. Each accepts `source=`. The caller selects the resource. A missing explicit input never triggers a search for an alternative.

Experiment cleaning keeps col47 friction dP, L8 Re>=1600, and Shanghai source/geometry exclusion guards. CFD cleaning keeps raw Dh, nominal Re, pressure-density guards, entrance exclusions, and water flow-suspect flags.

```python
from sjtu_tpmshx.preprocess.offline import load_experiments, load_water

frame = load_experiments(source=training_workbook)
water = load_water('Diamond', source=water_workbook)
```

`fit_nu_sco2` reuses the existing log-space fit. The validation script keeps campaign splits, cross-validation, metrics, and CSV reports. Returned research coefficients require physical acceptance before adoption. This API never installs them as production correlations. Importing offline modules does not refit data.

On 2026-09-12, the user approved retirement of SurrogateV3/gamma research models, `publish_surrogate`, and `build_prebuilt_surrogate`. The [history index](history/legacy-models.md) keeps their col43/alpha pressure convention, publication contract, and tests at a fixed Git revision. The current col47 cleaner does not replace that historical calibration product.

Ordinary full preparation uses the fixed CFD resource. Tests prohibit workbook reading on that path. Quick Design evaluates analytical inlet-pressure fractions during preparation. The receiving solver consumes those recorded fractions. Only the fixed CFD method stays supported. Serialized preparation/solve and postprocess boundaries are unchanged.

`data-revision.txt` records the matching private data commit. The [data catalog](data-catalog.en.md) records active and historical paths. `Water-CFD/水数值模拟数据.xlsx` stays missing. The explicit legacy-water Nu check neither substitutes that file nor reconstructs its historical fit. The catalog keeps measured error and the decision to keep the original Nu correlation.

<a id="当前资源与研究输出"></a>

## Current resources and research outputs

Production coefficients come from `sjtu_tpmshx/models/nu_correlations.py`, `sjtu_tpmshx/configs/sco2_effective_nu.json`, `sjtu_tpmshx/df_surrogate/experimental_correction.py`, and `sjtu_tpmshx/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv`. The CSV is a runtime input. MMS order/boundary CSV files consumed by tests stay valid verification resources.

Offline review tools stay in `validation/`. Generated fit CSV files default to local `.cache/reports/df_refit/` and `.cache/reports/sco2_cfd/`. Investigation scripts, stage plans, and research results belong in ignored `.cache/`. Current instructions, model provenance, physical constraints, and effective tests stay tracked with code. The [history index](history/README.en.md#2026-09-18-历史材料整理) keeps earlier stage reports, task graphs, and fitted tables. Tree cleanup does not erase Git history or automatically adopt research candidates.

The fixed geometry/D-F table supports cell sizes of 4–8 mm and walls of 0.3–0.6 mm. Nu correlations and experimental corrections have separate evidence ranges. Geometry-table coverage cannot replace them. Water also starts from the fixed CFD resistance baseline. Only explicit experimental mode applies its experimental correction. Skipping the air-specific roughness algorithm does not mean CFD already includes experimental correction.

If the one-dimensional isothermal D-F approximation produces nonpositive outlet pressure squared, that approximation has no positive outlet-pressure solution. This does not show real flow choking. With `strict=True`, the interface returns NaN. Otherwise, it keeps inlet pressure as a placeholder for the pressure-drop calculation. Both paths record warnings. The placeholder is not a valid pressure-drop prediction.

<a id="sco2-有效-nu-系数"></a>

## sCO2 effective Nu coefficients

The sole current experimental-mode publication resource is [sco2_effective_nu.json](../sjtu_tpmshx/configs/sco2_effective_nu.json), version `sco2-effective-nu-20260920-v1`. The factory `models.nu_correlations.sco2_effective_nu_config()` reads it and returns a validated `Sco2NuConfig`. Callers do not keep another set of current default coefficients.

| Field | Current value | Meaning |
| --- | ---: | --- |
| `alpha_G` | 2.4824 | Gyroid total effective coefficient Ceff relative to the current CFD base correlation |
| `alpha_D` | 4.1064 | Diamond total effective coefficient Ceff relative to the current CFD base correlation |

The names `alpha_D/alpha_G` stay, but both mean **total Ceff**. The calculation is `Nu_selected = Ceff × Nu_base`, followed by existing constraints such as the Nu floor. The coefficient is applied one time. There is no production `beta` field or simultaneous estimate of two independent physical corrections. Ceff changes local Nu and heat-transfer coefficients.

A full solve then determines Q. Output Q is not simply multiplied by Ceff. Temperatures, properties, and velocities change between solves. Therefore, local h ratios need not be constant everywhere.

The GUI's Use Current Effective Coefficients action explicitly loads this version. Import still accepts custom/historical parameters with version, provenance, and applicability. API callers can select it in a complete input dictionary:

```python
from dataclasses import asdict
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.models.nu_correlations import sco2_effective_nu_config

config_dict["sco2_nu"] = asdict(sco2_effective_nu_config())
config = ComputeConfig.from_dict(config_dict)
```

The generic `cfd_smooth` default stays unchanged. Saved configurations and prepared Cases keep their actual model parameters. Loading an previous file does not apply current values or multiply historical alpha by current Ceff again. Parameter JSON records only Nu model selection and provenance. It is not a complete case and does not change grids or solver tolerances.

<a id="标定来源与目标"></a>

### Calibration source and objective

On 2026-09-20, calibration used Gyroid exchanger experiments from local `data/raw_data/experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx`. It adjusted the amplitude of the **current base correlation**. Only 30 development cases entered selection. The objective gives equal weight to each case's squared relative hot-side Q error:

```text
J(Ceff,G) = mean_i[(Q_model,i(Ceff,G) / Q_hot,exp,i − 1)²], i = 1..30
```

Each candidate fully updates flow, properties, and three-phase temperatures. Selection uses actual solves on the 104×24×12 grid. The objective is relative MSE, not MAPE or an apparent-h/mean-local-h ratio. Search coordinates normalized by the historical amplitude gave a relative multiplier of 2.32. Publication combined it into the total Ceff values above.

The previous amplitude is only a search coordinate and comparison, not another independent physical correction. At the user's direction, Diamond received the same relative adjustment. Diamond did not participate in Gyroid parameter selection and stays a transfer assumption.

The 30 development members are G2/4/5/6/7/8/9/11/12/13/14/15/17/18/19/20/21/23/24/25/26/28/29/31/32/34/35/36/38/40. After parameters froze, review used G3/10/16/22/33/39/41/42, eight cases. Earlier exploratory G27/G44 stay a separate two-case pilot group. Diamond transfer checks cover only D8/D27/D50. All historical Gyroid results had already been seen.

Earlier amplitude selection does not show independence from this dataset. This is retrospective grouped review, not a blind test or independent validation of the full correlation.

<a id="已有验证与剩余误差"></a>

### Existing validation and remaining error

These are complete paired results with the same source, 104×24×12 grid, and strict numerical settings. Each side keeps its own experimental Q denominator. MAPE is mean absolute relative error. Hot and cold errors are not combined. The previous-parameter comparison was recalculated for this pairing. It does not replace the original 83-case history.

| Group | Count | Hot Q MAPE, previous→current (%) | Cold Q MAPE, previous→current (%) |
| --- | ---: | ---: | ---: |
| Gyroid development | 30 | 16.304 → 3.414 | 23.224 → 8.458 |
| Gyroid holdout review in this round | 8 | 17.541 → 2.500 | 24.913 → 11.224 |
| Gyroid previously used pilots | 2 | 14.837 → 1.153 | 25.521 → 11.538 |
| Diamond transfer with the same multiplier | 3 | 29.419 → 18.547 | 31.739 → 21.231 |

Among eight review cases, six near 100 g/s have current hot/cold MAPE of 1.035%/10.260%. The higher cold-inlet-temperature cases G41/G42 have 6.896%/14.116%. G41 has the worst hot-side error, −9.333%. Input-group differences do not isolate temperature causally. They were not used to retune frozen coefficients.

Different experimental hot/cold duties cannot both exactly match one conservative core output. Better hot-side accuracy does not remove cold-side bias. Three Diamond cases keep substantial error. These results do not qualify all 43 cases or other topologies.

With current coefficients fixed, refining G8/G13 to 208×48×24 increases Q by 0.721%/0.522%. Q spans at the corresponding actual search neighbors are 0.668%/0.692%. Only two development cases received this comparison. It does not show grid independence for the full group. Decimal places are not physical accuracy or statistical confidence intervals.

These checks use outer temperature tolerance 0.001 K, SIMPLE momentum 1e−5, and local/global mass 1e−7. Enthalpy update tolerance is 1e−6. Coupling and three-phase equation energy tolerances are each 1e−5. Enthalpy budget is 1000×25 with relaxation 0.6. Each outer step converged without enthalpy clipping.

Numerical qualification and experimental accuracy are separate. Importing parameter JSON does not enable these strict settings. Other default grids or tolerances cannot inherit the measured results above. Raw inputs, native fields, and investigation reports stay in local ignored directories and are not published with usage documentation.

<a id="物理范围与历史入口"></a>

### Physical scope and historical entries

The evidence covers uniform, symmetric D/G 7 mm cells, 0.6 mm walls, and a 182×42×42 mm core. Both streams are sCO2. It uses current variable properties and pressure treatment, existing partial cold-side ports, and the 104×24×12 model. Gyroid development hot/cold inlet temperatures span 128.640–230.827 °C / 96.815–135.347 °C. Absolute inlet pressures span 8.278–9.116 MPa / 9.437–10.725 MPa.

These are sample bounds. The qualification does not include all combinations inside them. D-F, enthalpy, properties, and base CFD correlations keep their own applicability limits.

Ceff is an effective amplitude for this device and homogenized model. It can absorb correlation extrapolation, internal temperature-difference allocation, discretization, and measurement-scope differences. The fit cannot uniquely separate these causes. It does not show correct local Nu, wall temperatures, or complete temperature fields. It is not a general correction for other geometries, mixed fluids, or arbitrary low-Pr conditions. Different grids, discretizations, devices, or operating ranges require renewed review.

Former D/G=1.77/1.07 and anchored γ≈1.809/1.130 stay only to interpret historical models and saved inputs. Previous gamma helpers, environment switches, and dedicated refitting/temperature-sweep tools are retired. See the fixed [old sCO2 Nu anchor route](history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20). Base CFD formulas, fitting/loading/cleaning tools, and experimental Q diagnostics stay. D-F coefficients are unchanged.

<a id="上海-gyroid-空气阻力标定"></a>

## Shanghai Gyroid air resistance calibration

The production value is `sF = 2.649010286988306`, version `shanghai-air-straight-20260401-v1`. It corrects the inertial term of the fixed CFD baseline. Baseline values are `K0 = 5.370404288696783e-8 m²` and `cF0 = 199.05002405781562 m⁻¹`. Corrected `cF = sF × cF0 = 527.2855613544234 m⁻¹`. K0 stays unchanged.

The source is `water-air_G7-t0p6_shanghai_experiment_20260401.xlsx` under local `data/raw_data/experiments/water_air/`. It uses `Sheet1` rows 4–18, cases 2–16. On April 1, air travels straight along +x. Water uses staggered openings along −y. On April 7, air and water exchange channels while the specimen and other piping stay unchanged. That dataset is for transfer validation only and does not enter this fit.

| Input | Source fields and conversion |
| --- | --- |
| Mass flow | Nominal mass flow in F, kg/s |
| Temperature | AC/AD inlet/outlet temperatures in °C, converted to K and averaged |
| Pressure | AE/AF gauge pressures in Pa, each increased by 101325 Pa for absolute pressure |
| Area and length | Single-channel area A = 6.50e-4 m². L = 0.182 m |
| Air properties | R = 287.05 J/(kg K). Current air_viscosity evaluates μ at mean temperature |

With `T̄ = (Tin + Tout)/2` and `G = ṁ/A`, the one-dimensional compressible model is:

```text
Pout² = Pin² − 2 R T̄ L (μ G/K0 + sF cF0 G²)
Δp_pred = Pin − sqrt(Pout²)
Objective = mean((Δp_pred/Δp_exp − 1)²)
```

K0 is fixed. Only sF is fitted. Existing Δp ≥ 2000 Pa and duplicate-row exclusions stay. Low-flow case 1 lies outside the calibration range. Its calculation, extrapolation notice, and separate error stay.

It does not enter conclusions for cases 2–16. `python -m sjtu_tpmshx.validation.df_refit.fit_experimental_effective` recalculates from the workbook. It outputs source file, sheet, row, and reviewed coefficients without overwriting production parameters.

The geometry is a uniform, symmetric Gyroid 7/0.6 mm, 182×42×42 mm exchanger, without zones and with δ=0. [Architecture constraints](architecture.md) still validate ports and other physical limits. This effective resistance correction belongs to this experiment and model convention. It is not a universal fluid constant independent of device, area, or pressure definition.

| Velocity convention | Air pore-velocity range (m/s) |
| --- | --- |
| Original one-dimensional calibration | 8.026110584256458–22.441995588974073 |
| Formal inlet-density/pore-area convention for calibration extrapolation notices | 8.027855328062564–22.446874107951544 |
| Approved computable range | 3.912822900405603–24.546710397710296 |

Coefficient selection follows the air side. Existing nine ordered air/water/sCO₂ pairings still depend on per-side physical checks for computability. Experimental accuracy is shown only for reviewed air–water cases. Air–air and air–sCO₂ do not inherit equal accuracy. Runs outside the calibration window but inside the permitted computational range continue with an extrapolation notice.

The correction is applied one time across pressure initialization, SIMPLE, and prepared Case resources. Previous Case replay uses saved model parameters without applying the new table again. No extra common multiplier from earlier research is adopted. This documentation work changes no coefficients, ranges, or numerical thresholds for other topologies or fluids.
