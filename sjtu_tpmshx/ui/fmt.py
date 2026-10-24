"""Display formatting for durations, preset names and recorded qualification."""
from __future__ import annotations







def preset_display(name):
    """De-branded DISPLAY name for a preset (2026-07-03 user request):
    the internal key keeps its historical 'Shanghai (…)' spelling (presets
    dict, session files, tests), but every user-visible surface (command
    palette, status bar, session overview) shows 算例工况 instead."""
    if not name:
        return name
    return str(name).replace("Shanghai", "算例工况")


def duration(seconds):
    """'8.4s' / '2m15s' / '1h12m'."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return '—'
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int((s % 3600) // 60):02d}m"


def qualification_reasons(qualification, evidence=None):
    """Explain recorded gates without changing their verdicts."""
    labels = dict(execution='计算未完成', convergence='数值收敛未通过',
                  physical='物理台账未通过', applicability='关联式适用范围未通过',
                  metrics='性能指标不完整', model_scope='模型适用性未核实',
                  full_solve='缺少完整求解')
    reasons = []
    for key in qualification.get('design', {}).get('reasons', []):
        if key != 'applicability':
            reasons.append(labels.get(key, key))
            continue
        checks = qualification.get('applicability', {}).get('checks', [])
        for row in checks:
            if row.get('passed') is True:
                continue
            source = row.get('source', [])
            source = [{'nu_raw': 'Nu（原始输入）', 'nu': 'Nu（计算输入）',
                       'water': '水', 'air': '空气'}.get(item, item) for item in source]
            text = f"{row.get('side', '?')} 侧 {' '.join(source)} {row.get('quantity', '')}"
            text += ' 超范围' if row.get('passed') is False else ' 未核实'
            for sample in (evidence or {}).get(row.get('group'), []):
                if (sample.get('side') == row.get('side')
                        and sample.get('source') == row.get('source')
                        and sample.get('quantity') == row.get('quantity')
                        and sample.get('captured')):
                    from sjtu_tpmshx.domain.range_policy import assess_range
                    assessed = assess_range(sample)
                    if sample.get('minimum') is not None and sample.get('maximum') is not None:
                        lo, hi = assessed['allowed_bounds']
                        text += (f"（实际 {sample['minimum'][0]:.6g}–{sample['maximum'][0]:.6g}；"
                                 f"允许 {lo:.6g}–{hi:.6g}）")
                    break
            reasons.append(text)
        if not checks:
            reasons.append(labels[key])
    return list(dict.fromkeys(reasons))
