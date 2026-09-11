# Offline models and ordinary Case preparation

`sjtu_tpmshx.preprocess.offline` is the explicit offline entry point. It reuses
the existing experiment, water CFD, sCO2 core and sCO2 segment cleaners.
Each accepts `source=`; omitted paths preserve legacy behavior. Explicit sCO2
files must match the selected topology and core/segment layout. The caller
selects the resource; the loader does not search for an alternative on failure.

Experiment cleaning retains col47 friction dP, L8 Re>=1600 and the Shanghai
exclusion guards. SurrogateV3 calibration separately retains its col43/alpha
compressible pressure convention. These are distinct historical data products;
this extraction does not replace one with the other. CFD cleaning retains raw
Dh and nominal Re alongside the repository reductions, pressure-density guards,
entrance-period exclusions and water flow-suspect flags.

```python
from sjtu_tpmshx.preprocess.offline import load_experiments, publish_surrogate
from sjtu_tpmshx.df_surrogate.surrogate_v3 import SurrogateV3

frame = load_experiments(source=training_workbook)
manifest = publish_surrogate(training_workbook, new_output_directory,
                             data_revision=recorded_data_revision)
model = SurrogateV3('Diamond', calibration_csv=manifest.parent / 'Diamond.csv')
```

Publication requires a new caller-selected directory and an explicit revision
label. It writes derived points and a manifest, never raw measurements. The
label records the caller's data version; it is not a new raw-data authority.
Explicit missing inputs fail instead of falling back. No production resource
or repository coefficient table is replaced. Existing default SurrogateV3
source selection remains unchanged for its legacy callers. The existing
`df_surrogate.build_prebuilt_surrogate` command remains an explicit legacy
publication command and is never called by ordinary Case preparation.

`fit_nu_sco2` reuses the existing log-space fit. The validation script delegates
to it and retains campaign splits, cross-validation, metrics and CSV reports.
Returned research coefficients require their existing physical acceptance
before promotion; this API does not install them as production correlations.
Other validation/refit reports retain their existing entry points and output
responsibility. No automatic refit occurs simply by importing offline modules.

Ordinary full-mode preparation uses the versioned fixed CFD resource and is
tested with workbook reading/calibration forbidden. Quick-design's analytical
inlet-pressure evaluation also occurs in preparation. Even if a selected legacy
research mode initializes calibration while preparing, the receiving solver
only consumes the recorded pressure fractions. Ordinary defaults use the fixed
CFD table; selecting a research mode does not promote its model to production.

Data revision checked locally: ddf11acdf6c05340fb832e427d3861d0534bd934.
The data repository's selected experiment and sCO2 files were clean. The
current Water-CFD/水数值模拟数据.xlsx is absent there; the older water-cfd-raw.xlsx
is not substituted. Real water revalidation remains not run.
