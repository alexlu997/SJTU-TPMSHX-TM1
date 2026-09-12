# Offline models and ordinary Case preparation

`sjtu_tpmshx.preprocess.offline` exposes the experiment, water CFD, sCO2 core
and sCO2 segment cleaners. Each accepts `source=`. The caller selects the
resource; a missing explicit input never triggers a search for an alternative.

Experiment cleaning retains col47 friction dP, L8 Re>=1600 and Shanghai
source/geometry exclusion guards. CFD cleaning retains raw Dh and nominal Re,
pressure-density guards, entrance exclusions and water flow-suspect flags.

```python
from sjtu_tpmshx.preprocess.offline import load_experiments, load_water

frame = load_experiments(source=training_workbook)
water = load_water('Diamond', source=water_workbook)
```

`fit_nu_sco2` reuses the existing log-space fit. The validation script retains
campaign splits, cross-validation, metrics and CSV reports. Returned research
coefficients need physical acceptance before promotion; this API never installs
them as production correlations. Importing offline modules does not refit data.

On 2026-09-12 the user approved retiring SurrogateV3/gamma research models and
`publish_surrogate`, together with `build_prebuilt_surrogate`. Their original
col43/alpha pressure convention, publication contract and tests are preserved
at the fixed Git state in the [history index](../../../history/legacy-models.md).
The current col47 cleaner does not replace that historical calibration product.

Ordinary full preparation uses the fixed CFD resource and is tested with
workbook reading forbidden. Quick-design evaluates analytical inlet-pressure
fractions in preparation; the receiving solver uses the recorded fractions.
Only the fixed CFD method is now supported. Serialized preparation/solve and
postprocess boundaries are unchanged.

The matching private data commit is recorded by `data-revision.txt`; the
[data catalog](../../../data-catalog.md) records active and historical paths.
`Water-CFD/水数值模拟数据.xlsx` remains missing. The explicit legacy-water Nu
check does not substitute that file or reconstruct its historical fit; its
measured error and the decision to retain the original Nu are in the catalog.
