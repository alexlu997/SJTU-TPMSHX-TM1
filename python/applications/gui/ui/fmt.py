"""Display formatting for durations, preset names and recorded qualification."""
from __future__ import annotations

import math


def preset_display(name):
    """De-branded display name for a preset while keeping internal keys unchanged."""
    if not name:
        return name
    return str(name).replace("Shanghai", "默认算例")


def display_number(text, scale=1.0):
    """Format a numeric string to 6 significant digits for unfocused display."""
    try:
        value = float(text) * scale
    except (TypeError, ValueError):
        return str(text)
    if not math.isfinite(value):
        return str(text)
    if value != 0 and (abs(value) >= 1e6 or abs(value) < 1e-3):
        return f"{value:.5e}"
    if value.is_integer() and abs(value) < 1e6:
        return str(int(value))
    return f"{value:.6g}"


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


def recorded_elapsed_s(result) -> float | None:
    """Return the single recorded solve duration in seconds, or None if unrecorded."""
    if result is None:
        return None
    diag = getattr(result, "diagnostics", None)
    if isinstance(diag, dict):
        ws = diag.get("wall_time_s")
        if isinstance(ws, (int, float)) and not isinstance(ws, bool) and math.isfinite(ws):
            return float(ws)
    meta = getattr(result, "metadata", None)
    if isinstance(meta, dict):
        timings = meta.get("timings_s")
        if isinstance(timings, dict):
            total = timings.get("total")
            if (
                isinstance(total, (int, float))
                and not isinstance(total, bool)
                and math.isfinite(total)
            ):
                return float(total)
            phases = [
                float(timings[k])
                for k in ("prepare", "solve", "postprocess")
                if isinstance(timings.get(k), (int, float))
                and not isinstance(timings.get(k), bool)
                and math.isfinite(timings.get(k))
            ]
            if len(phases) == 3:
                return sum(phases)
    return None


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
                    from tm1.physical_models.range_policy import assess_range
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


def warning_strip_summary(summary: dict) -> str:
    """Summarize recorded warnings in Chinese for the compact bottom readout strip."""
    qualification = summary.get('qualification') or {}
    reasons = qualification_reasons(qualification, summary.get('applicability_evidence'))
    specific = [
        r.split('（实际 ')[0].strip()
        for r in reasons
        if r.strip() and r.strip() != '关联式适用范围未通过'
    ]
    if specific:
        first = specific[0]
        if len(specific) > 1:
            return f"{first}（共 {len(specific)} 项）"
        return first
    if summary.get('envelope_valid') is False:
        return "压缩性包络超出适用范围"
    warnings = [str(w).strip() for w in (summary.get('warnings') or []) if str(w).strip()]
    if not warnings:
        return "请核查诊断详情"
    first_raw = warnings[0]
    lower = first_raw.lower()
    if '[water nu' in lower:
        base = "水侧 Nu 关联式超出适用范围"
    elif '[nu extrap]' in lower:
        base = "空气侧 Nu 关联式外推"
    elif 'air_cp' in lower or 'air_mu' in lower or 'air_k' in lower:
        base = "空气物性超出拟合温区"
    elif 'water' in lower and ('range' in lower or 'extrap' in lower):
        base = "水物性或关联式超出适用范围"
    elif 'sco2' in lower or 'co2' in lower:
        base = "CO₂ 物性或关联式存在提示"
    elif any('\u4e00' <= ch <= '\u9fff' for ch in first_raw):
        base = first_raw.split('（')[0].strip()
        if len(base) > 36:
            base = base[:35] + '…'
    else:
        base = f"存在 {len(warnings)} 条计算提示，请查看诊断"
    if len(warnings) > 1 and '共 ' not in base and '条计算提示' not in base:
        return f"{base}（共 {len(warnings)} 项）"
    return base
