"""Publish derived SurrogateV3 points without changing production resources."""
import json
from pathlib import Path

from sjtu_tpmshx.df_surrogate.surrogate_v3 import SurrogateV3


def publish_surrogate(training_workbook, output_directory, *, data_revision):
    """Use the existing col43/alpha calibration, never silently fall back to CSV."""
    if not isinstance(data_revision, str) or not data_revision.strip():
        raise ValueError('an explicit source data revision is required')
    source = Path(training_workbook).resolve()
    output = Path(output_directory)
    models = {tpms: SurrogateV3(tpms, training_workbook=source)
              for tpms in ('Diamond', 'Gyroid')}
    # Fit both before creating a publication, so a missing sheet cannot leave
    # a report claiming that both topologies were calibrated.
    output.mkdir(parents=True, exist_ok=False)
    report = dict(format='surrogate_v3_calibrated_points_v1',
                  source_workbook=str(source), data_revision=data_revision,
                  method='rbf', pressure_basis='col43_alpha',
                  units={'L_mm': 'mm', 't_mm': 'mm', 'eps_f': '1',
                         'K': 'm2', 'c_F': '1/m'}, models={})
    for tpms, model in models.items():
        path = model.dump_prebuilt(output / f'{tpms}.csv')
        report['models'][tpms] = dict(file=path.name, geometries=len(model.ref))
    manifest = output / 'manifest.json'
    manifest.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return manifest
