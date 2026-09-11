"""Compare all declared fixed jobs; never replace the denominator with successes."""
import argparse
import json
import math
from pathlib import Path


def equal(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


assert equal({'a': [float('nan')]}, {'a': [float('nan')]})
assert not equal({'a': 1.}, {'a': 1.0001})
parser = argparse.ArgumentParser()
parser.add_argument('manifest', type=Path)
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
jobs = json.loads(args.manifest.read_text())['jobs']
assert len(jobs) == 166
roots = (args.baseline, args.candidate)
rows = []
for job in jobs:
    row = dict(id=job['id'], topology=job['topology'], dimension=job['dimension'], split=job['split'])
    paths = [r/(job['id']+'.json') for r in roots]
    row['present'] = [p.exists() for p in paths]
    if all(row['present']):
        a, b = [json.loads(p.read_text()) for p in paths]
        row['execution'] = [a['execution'], b['execution']]
        if all(r['execution'] == 'completed' for r in (a, b)):
            row.update(config_equal=equal(a['config'], b['config']),
                       converged=[a['converged'], b['converged']],
                       warnings_equal=equal(a['warnings'], b['warnings']),
                       absolute_difference={k:b['raw_metrics'][k]-v for k,v in a['raw_metrics'].items()},
                       relative_difference={k:abs(b['raw_metrics'][k]-v)/max(abs(v),1.) for k,v in a['raw_metrics'].items()},
                       lost_diagnostic_keys=sorted(a['diagnostics'].keys()-b['diagnostics'].keys()),
                       changed_common_diagnostic_keys=[k for k in a['diagnostics'] if k in b['diagnostics'] and not equal(a['diagnostics'][k],b['diagnostics'][k])])
            # Original fixed-set quality definition uses measured 0.042 m depth.
            factor = .042 if job['dimension'] == '2d' else 1.
            row['experimental_Q_error_rel'] = [r['raw_metrics']['Q_W']*factor/float(job['reference_record']['Q_ref_W'])-1 for r in (a,b)]
            old_context = ('stage=main, layout=solver-cell(perp,stream)' if job['dimension']=='2d'
                           else 'stage=df-application, layout=scalar')
            new_context = ('stage=prepared-df, layout=solver-row' if job['dimension']=='2d'
                           else 'stage=prepared-df, layout=scalar')
            row['warning_multiset_equal_after_documented_df_context_move'] = equal(
                sorted(w.replace(old_context,new_context) if w.startswith('[D-F extrap]') else w for w in a['warnings']),
                sorted(b['warnings']))
    rows.append(row)
groups=[]
for topology, count in [('Diamond',43),('Gyroid',40)]:
    for dimension in ('2d','3d'):
        selected=[r for r in rows if (r['topology'],r['dimension'])==(topology,dimension)]
        assert len(selected)==count
        complete=all('experimental_Q_error_rel' in r for r in selected)
        groups.append(dict(topology=topology,dimension=dimension,expected=count,
            paired_completed=sum('experimental_Q_error_rel' in r for r in selected),
            Q_RMSRE=[math.sqrt(sum(r['experimental_Q_error_rel'][i]**2 for r in selected)/count) for i in (0,1)] if complete else None))
result=dict(expected=166, paired_completed=sum('experimental_Q_error_rel' in r for r in rows),
            provenance=[json.loads((r/'provenance.json').read_text()) for r in roots],groups=groups,rows=rows)
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','provenance')},indent=2))
