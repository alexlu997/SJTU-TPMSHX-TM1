"""Human-readable results with numerical state alongside each metric set."""
from html import escape
import json

from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.io.text_file import write_text


def write_report(result, performance, path):
    if performance.source_result_id != result.result_id:
        raise ValueError('performance and field result identifiers disagree')
    rows = []
    for name, metric in performance.metrics.items():
        value = format(metric.value, '.10g') if metric.value is not None else 'unavailable'
        rows.append('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in
                    (name, value, metric.spec.unit, metric.status, metric.reason)) + '</tr>')
    diagnostics = result.metadata.get('diagnostics', {})
    warnings = diagnostics.get('warnings_list', diagnostics.get('warnings', ()))
    status = escape(json.dumps(mutable_data(result.run_status), ensure_ascii=False, indent=2))
    html = ('<!doctype html><meta charset="utf-8"><title>TPMS result report</title>'
            '<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 20px}'
            'table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;text-align:left}'
            'pre{white-space:pre-wrap}</style>'
            f'<h1>Result {escape(result.result_id)}</h1><p>Case {escape(result.case_id)}</p>'
            '<p>Numerical results; metric availability does not establish experimental accuracy.</p>'
            f'<h2>Run status</h2><pre>{status}</pre>'
            '<h2>Metrics</h2><table><thead><tr><th>Name</th><th>Value</th><th>Unit</th><th>Status</th><th>Reason</th></tr></thead>'
            '<tbody>' + ''.join(rows) + '</tbody></table><h2>Warnings</h2><ul>'
            + ''.join(f'<li>{escape(str(warning))}</li>' for warning in warnings) + '</ul>')
    return write_text(path, html)
