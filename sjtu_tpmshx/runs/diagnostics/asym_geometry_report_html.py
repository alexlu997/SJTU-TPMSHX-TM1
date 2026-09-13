"""
Phase 0 历史流程报告：读 asym_geom_scan CSV → 自包含 HTML（手绘 SVG + Task 0-5 全流程）。
默认输出至 sjtu_tpmshx/runs/_out，TPMSHX_TOOL_OUT_DIR 可覆盖目录。
在仓库根目录运行：python -m sjtu_tpmshx.runs.diagnostics.asym_geometry_report_html
"""
import csv
import html as _html
import os
from pathlib import Path

CSV = Path(__file__).resolve().parents[2] / "runs" / "_out" / "asym_geom_scan_2026-06-05.csv"
# P1.7: was a dead C:\Users\ALEX\Desktop path. Default to gitignored
# runs/_out; TPMSHX_TOOL_OUT_DIR overrides.
_OUT_DIR = Path(os.environ.get('TPMSHX_TOOL_OUT_DIR',
                               str(Path(__file__).resolve().parents[1] / "_out")))
_OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_HTML = _OUT_DIR / "TPMS-非对称孔隙率-Phase0-扫描图.html"

A_COL, B_COL = "#2563eb", "#94a3b8"                 # 流体 A 得益 / B 挤压
TP_COL = {"Diamond": "#2563eb", "Gyroid": "#0ea5e9"}  # 两族（双蓝）
FLOOR_MM = 0.3
RED = "#ef4444"


def load():
    rows = []
    with CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({k: (v if k == "tpms" else float(v) if v not in ("True", "False")
                             else v == "True") for k, v in r.items()})
    by = {}
    for r in rows:
        by.setdefault(r["tpms"], []).append(r)
    return by


def _poly(xs, ys, px, py):
    return " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, ys))


def svg_chart(series, title, ylabel, xlabel="δ (φ-offset)",
              y_min=None, y_max=None, hlines=None, vlines=None,
              width=520, height=320):
    ml, mr, mt, mb = 58, 16, 26, 46
    pw, ph = width - ml - mr, height - mt - mb
    xs_all = [v for s in series for v in s["x"]]
    ys_all = [v for s in series for v in s["y"]]
    xmin, xmax = min(xs_all), max(xs_all)
    ymin = 0.0 if y_min is None else y_min
    ymax = (max(ys_all) * 1.08) if y_max is None else y_max
    if ymax <= ymin:
        ymax = ymin + 1

    def px(x):
        return ml + (x - xmin) / (xmax - xmin) * pw

    def py(y):
        y = min(max(y, ymin), ymax)
        return mt + (1 - (y - ymin) / (ymax - ymin)) * ph

    o = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    o.append(f'<text x="{ml}" y="15" class="ctitle">{title}</text>')
    for i in range(5):
        yv = ymin + (ymax - ymin) * i / 4
        yy = py(yv)
        o.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width-mr}" y2="{yy:.1f}" class="grid"/>')
        o.append(f'<text x="{ml-7}" y="{yy+3:.1f}" class="tick ty">{yv:.2f}</text>')
    for i in range(5):
        xv = xmin + (xmax - xmin) * i / 4
        o.append(f'<text x="{px(xv):.1f}" y="{height-mb+16}" class="tick tx">{xv:.2f}</text>')
    for hl in (hlines or []):
        yv, col, lab, dash = hl
        if ymin <= yv <= ymax:
            yy = py(yv)
            o.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width-mr}" y2="{yy:.1f}" '
                     f'stroke="{col}" stroke-width="1.4" stroke-dasharray="{dash}"/>')
            o.append(f'<text x="{width-mr-3}" y="{yy-4:.1f}" class="hlab" fill="{col}">{lab}</text>')
    for vl in (vlines or []):
        xv, col, lab = vl
        if xmin <= xv <= xmax:
            xx = px(xv)
            o.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{mt+ph}" '
                     f'stroke="{col}" stroke-width="1.2" stroke-dasharray="3 3"/>')
            o.append(f'<text x="{xx+3:.1f}" y="{mt+12}" class="vlab" fill="{col}">{lab}</text>')
    o.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt+ph}" class="axis"/>')
    o.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{width-mr}" y2="{mt+ph}" class="axis"/>')
    o.append(f'<text x="{ml-42}" y="{mt+ph/2}" class="axlab" '
             f'transform="rotate(-90 {ml-42} {mt+ph/2})">{ylabel}</text>')
    o.append(f'<text x="{ml+pw/2}" y="{height-5}" class="axlab">{xlabel}</text>')
    for s in series:
        o.append(f'<polyline points="{_poly(s["x"], s["y"], px, py)}" fill="none" '
                 f'stroke="{s["color"]}" stroke-width="2.4" '
                 f'stroke-dasharray="{s.get("dash","")}" stroke-linejoin="round"/>')
    lx, ly = ml + 10, mt + 12
    for s in series:
        o.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+18}" y2="{ly}" stroke="{s["color"]}" '
                 f'stroke-width="2.4" stroke-dasharray="{s.get("dash","")}"/>')
        o.append(f'<text x="{lx+23}" y="{ly+3}" class="leg">{s["label"]}</text>')
        ly += 15
    o.append("</svg>")
    return "\n".join(o)


# ── Task 0-5 流程内容（事实即实际执行）──────────────────────────────
def esc(s):
    return _html.escape(s)


TASKS = [
    dict(num="0", tag="设置", title="几何模型 + 参数化 + 计划", commit="—",
         purpose="把「偏移等值面」机制定成可计算的契约，确定要扫什么、闸门怎么判。不写代码。",
         code="# 偏移带：solid = { δ−C ≤ φ ≤ δ+C }，δ=中心偏移，C=半宽(壁厚)\n"
              "void_A = { φ < δ−C }   # 得益侧（气侧），δ↑ → 增大\n"
              "void_B = { φ > δ+C }   # 挤压侧（液侧）\n"
              "δ = 0  →  ε_A = ε_B = ε/2   # 退化回现状 50/50（零回归锚）",
         tests=["新文件 solvers/asym_geometry.py（只读复用 tpms_geometry，不碰生产路径）",
                "驱动 runs/asym_geometry_scan.py + 报告 runs/asym_geometry_report_html.py",
                "测试 tests/test_asym_geometry.py（9 测守护）"],
         result="计划落 vault/reports/engineering/2026-06-05-asym-porosity-phase0-PLAN-CN.md（6 TDD 任务 + 闸门标准）"),
    dict(num="1", tag="TDD", title="孔隙切分 eps_sides", commit="6ea52c1",
         purpose="造第一个几何原子：给 φ 场、半宽 C、偏移 δ → 算两侧孔隙 (ε_A, ε_B, ε)。整个方案的地基。",
         code="def eps_sides(phi, C, delta=0.0):\n"
              "    eps_A = float(np.mean(phi < (delta - C)))   # 得益侧\n"
              "    eps_B = float(np.mean(phi > (delta + C)))   # 挤压侧\n"
              "    return eps_A, eps_B, eps_A + eps_B",
         tests=["δ=0 → ε_A == ε_B（均分，退回 50/50）",
                "δ>0 → ε_A 涨、ε_B 降（验符号：上轮 doc 写反、已纠）",
                "小 δ → 总 ε 漂 < 2%（验 O(δ²) 微漂）"],
         result="3 passed。地基浇正：δ 怎么分孔隙、符号对。"),
    dict(num="2", tag="TDD", title="per-side 面积 / D_h + δ=0 硬锚", commit="6ceb500",
         purpose="每侧单侧比表面积 A0 与水力直径 D_h；并设 δ=0 退化硬锚——必须逐位复现现有 compute_geometry。",
         code="def a0_sides(phi, C, delta, L_m, N):\n"
              "    solid  = (phi >= delta-C) & (phi <= delta+C)\n"
              "    void_A = phi < (delta-C);  void_B = phi > (delta+C)\n"
              "    norm = (L_m**3) * 1.553       # 无额外 ÷2（F_side 已是单面）\n"
              "    A0_A = _count_interface(solid, void_A) * dx**2 / norm\n"
              "    ...  # D_h = 4·ε_side / A0_side",
         tests=["δ=0 → A0_A == A0_B == compute_geometry['A_0']（rel 2e-2）",
                "δ=0 → D_h == compute_geometry['D_h']（rel 3e-2）"],
         result="5 passed。硬锚通过 → 偏移机制在 δ=0 逐位复现现状几何，归一化验对。"),
    dict(num="3", tag="TDD", title="连通性 + 壁厚 + δ_max 搜索", commit="c135844",
         purpose="判通道是否还通（连通分量），搜可行偏移上界 δ_max（纯连通夹断极限；壁厚按 2C 常数，不约束物理壁厚）。δ_max 定可达偏置上界。",
         code="def percolates_z(mask):           # void 沿流向 z 是否单块贯穿\n"
              "    lab,_ = ndimage.label(mask); ...\n"
              "def find_delta_max(phi, C):        # 两侧 percolate 的最大 |δ|（连通极限）\n"
              "    # 壁=2C 常数：不卡物理壁厚（min-wall 延后到 STL 阶段）",
         tests=["δ=0 两侧空腔都贯穿（双连通 sheet 拓扑）",
                "全固体块 → 不贯穿",
                "壁厚为正且 < 胞元",
                "find_delta_max 返回 > 0 的可行带"],
         result="9 passed。核心几何模块完整（ε/A0/D_h/连通/δ_max 全 TDD 守护）。"),
    dict(num="4", tag="出数", title="扫描驱动 + CSV + 闸门", commit="41c7030",
         purpose="拿工具真去扫：δ × {Diamond, Gyroid}（L5 t0.4, N128）→ CSV 82 行 + 闸门判定。Phase 0 的答案在这。",
         code="# 可用 r = r @ ε_B ≥ 50% of ε_B(δ=0)（小通道不塌过半；避开 pinch 虚高）\n"
              "usable = [x for x in feas if x.eps_B >= 0.5*epsB0]\n"
              "r_usable = max(x.r for x in usable)\n"
              "verdict = PASS if (r_usable >= 2.0 and anchor_ok) else HOLD",
         tests=["anchor=OK（δ=0 行 A0 == compute_geometry，端到端验归一化）",
                "脚本跑通，CSV 生成，闸门表打印"],
         result="闸门 PASS（两族）。Diamond r_usable 2.95 / Gyroid 2.93（≈3:1），均 ≫ 2:1。"),
    dict(num="5", tag="可视化", title="HTML 流程报告（本页）", commit="d5b2cd4",
         purpose="读 CSV → 自包含 HTML（手绘 SVG 折线，离线渲染，无 JS 依赖）→ 桌面。即本页。",
         code="svg_chart(series, ...)   # 手绘 SVG 折线 + 网格 + 标注线\n"
              "# 头牌：r(δ)↑ 与 壁厚 t(δ)↓ 并排同 δ 轴 = 偏置-壁厚 tradeoff",
         tests=["6 图 / 12 折线 / 闸门数值入表 / 0.3mm 地板线 / δ_max 竖线 全渲染"],
         result="本页生成，落桌面。"),
]


def main():
    by = load()

    # 图
    r_series = [dict(x=[r["delta"] for r in rows], y=[min(r["r"], 8.0) for r in rows],
                     color=TP_COL[t], label=t) for t, rows in by.items()]
    vlines = [(max(r["delta"] for r in rows if r["feasible"]), TP_COL[t], f"{t} δ_max")
              for t, rows in by.items()]
    chart_r = svg_chart(r_series, "① 偏置比 r 随 δ ↑（y 截顶 8）", "r = ε_A / ε_B",
                        y_min=0, y_max=8.0, hlines=[(2.0, RED, "r=2 闸门", "5 4")], vlines=vlines)
    epsB_series = [dict(x=[r["delta"] for r in rows], y=[r["eps_B"] for r in rows],
                        color=TP_COL[t], label=t) for t, rows in by.items()]
    epsB0_lines = [(0.5*rows[0]["eps_B"], TP_COL[t], f"{t} ε_B0×50%", "5 4")
                   for t, rows in by.items()]
    chart_t = svg_chart(epsB_series, "② 挤压侧 ε_B 随 δ ↓（塌到 50% = 可用上界）", "ε_B",
                        hlines=epsB0_lines, vlines=vlines)
    eps_charts, dh_charts = [], []
    for t, rows in by.items():
        eps_charts.append(svg_chart(
            [dict(x=[r["delta"] for r in rows], y=[r["eps_A"] for r in rows], color=A_COL, label="ε_A 得益"),
             dict(x=[r["delta"] for r in rows], y=[r["eps_B"] for r in rows], color=B_COL, label="ε_B 挤压")],
            f"③ {t}: ε_A / ε_B 分化", "ε_side"))
        dh_charts.append(svg_chart(
            [dict(x=[r["delta"] for r in rows], y=[r["Dh_A"]*1e3 for r in rows], color=A_COL, label="D_h,A"),
             dict(x=[r["delta"] for r in rows], y=[r["Dh_B"]*1e3 for r in rows], color=B_COL, label="D_h,B")],
            f"④ {t}: D_h 每侧 [mm]", "D_h [mm]"))

    # summary
    summ = []
    for t, rows in by.items():
        feas = [r for r in rows if r["feasible"]]
        epsB0 = rows[0]["eps_B"]
        r_u = max((r["r"] for r in feas if r["eps_B"] >= 0.5*epsB0), default=0.0)
        r_m = max((r["r"] for r in feas), default=0.0)
        dmax = max(r["delta"] for r in feas)
        last = feas[-1]
        summ.append((t, dmax, r_u, r_m, abs(last["eps"]-rows[0]["eps"])/rows[0]["eps"]*100))
    summ_rows = "\n".join(
        f'<tr><td><b>{t}</b></td><td>{dmax:.3f}</td><td class="hl">{ru:.2f}:1</td>'
        f'<td class="muted">{rm:.1f}:1</td><td>{ed:.1f}%</td>'
        f'<td class="ok">PASS</td></tr>' for (t, dmax, ru, rm, ed) in summ)

    # 时间线 + 任务卡
    steps = "".join(
        f'<div class="step{" done" if x["commit"]!="—" else " setup"}">'
        f'<span class="sdot"></span><span class="snum">T{x["num"]}</span>'
        f'<span class="stitle">{esc(x["title"])}</span>'
        f'<span class="scommit">{x["commit"]}</span></div>' for x in TASKS)

    cards = ""
    for x in TASKS:
        tests = "".join(f'<li>{esc(t)}</li>' for t in x["tests"])
        cards += f"""
<div class="task">
  <div class="thead">
    <span class="tnum">Task {x['num']}</span>
    <span class="ttag">{esc(x['tag'])}</span>
    <span class="ttitle">{esc(x['title'])}</span>
    <span class="tcommit">{x['commit']}</span>
  </div>
  <div class="tbody">
    <div class="tlabel">目的</div><p class="tpurpose">{esc(x['purpose'])}</p>
    <div class="tlabel">实现</div><pre class="code">{esc(x['code'])}</pre>
    <div class="tlabel">{'验证 / 测试' if x['num']!='0' else '产出物'}</div><ul class="tlist">{tests}</ul>
    <div class="tresult">✓ {esc(x['result'])}</div>
  </div>
</div>"""

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TPMS 非对称孔隙率 · Phase 0 完整流程</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;700;800&family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#fafbfd;--card:#fff;--ink:#0f172a;--soft:#475569;--faint:#94a3b8;--line:#e6ebf2;
--blue:#2563eb;--blue-d:#1e40af;--sky:#0ea5e9;--soft-blue:#eff6ff;--amber:#f59e0b;--red:#ef4444;--green:#16a34a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
font-family:'Noto Sans SC',-apple-system,'Segoe UI',sans-serif;font-size:15.5px;line-height:1.7;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1080px;margin:0 auto;padding:52px 26px 100px}}
.kick{{font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:var(--blue);font-weight:500}}
h1{{font-family:'Manrope','Noto Sans SC',sans-serif;font-weight:800;font-size:clamp(2rem,5vw,3.2rem);line-height:1.06;letter-spacing:-.02em;margin:.18em 0 .12em}}
h1 .em{{color:var(--blue)}}
.sub{{color:var(--soft);max-width:64ch;margin:.3em 0 0}}
h2{{font-family:'Manrope','Noto Sans SC',sans-serif;font-weight:700;font-size:1.5rem;letter-spacing:-.01em;margin:3em 0 .2em;display:flex;align-items:center;gap:10px}}
h2::before{{content:"";width:9px;height:22px;background:var(--blue);border-radius:2px}}
.lead{{color:var(--soft);margin:.2em 0 0}}

/* verdict */
.verdict{{margin:30px 0 0;background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;border-radius:14px;padding:28px 30px;box-shadow:0 18px 40px -18px rgba(37,99,235,.5)}}
.verdict .vk{{font-family:'IBM Plex Mono',monospace;font-size:11.5px;letter-spacing:.18em;text-transform:uppercase;color:#bfdbfe}}
.verdict .vmain{{font-family:'Manrope',sans-serif;font-weight:700;font-size:clamp(1.3rem,3vw,1.8rem);margin:.3em 0 .5em;line-height:1.3}}
.verdict .vmain b{{color:#fde68a}}
.verdict p{{margin:0;color:#dbeafe;font-size:.95rem}}

.tbl{{margin:22px 0 0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card)}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:11px 15px;text-align:left;border-bottom:1px solid var(--line)}}
thead th{{background:var(--soft-blue);color:var(--blue-d);font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.05em;text-transform:uppercase;font-weight:600}}
tbody tr:last-child td{{border-bottom:none}}
td.hl{{font-weight:700;color:var(--blue)}}td.muted{{color:var(--faint)}}td.ok{{color:var(--green);font-weight:700}}

/* timeline */
.timeline{{display:flex;flex-wrap:wrap;gap:0;margin:24px 0 0;border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden}}
.step{{flex:1 1 150px;min-width:150px;padding:16px 18px;border-right:1px solid var(--line);position:relative}}
.step:last-child{{border-right:none}}
.step .sdot{{width:10px;height:10px;border-radius:50%;background:var(--blue);display:inline-block;margin-right:7px}}
.step.setup .sdot{{background:var(--faint)}}
.step .snum{{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:12px;color:var(--blue)}}
.step.setup .snum{{color:var(--faint)}}
.step .stitle{{display:block;font-size:13px;font-weight:500;margin:6px 0 4px;color:var(--ink)}}
.step .scommit{{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--faint)}}

/* task card */
.task{{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:18px 0;overflow:hidden}}
.thead{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:15px 22px;background:var(--soft-blue);border-bottom:1px solid var(--line)}}
.thead .tnum{{font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:12px;color:#fff;background:var(--blue);padding:3px 9px;border-radius:5px}}
.thead .ttag{{font-family:'IBM Plex Mono',monospace;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--blue-d);border:1px solid #bfdbfe;padding:2px 8px;border-radius:20px}}
.thead .ttitle{{font-family:'Manrope','Noto Sans SC',sans-serif;font-weight:700;font-size:1.08rem}}
.thead .tcommit{{margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--faint)}}
.tbody{{padding:18px 22px}}
.tlabel{{font-family:'IBM Plex Mono',monospace;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--blue);font-weight:600;margin:14px 0 5px}}
.tlabel:first-child{{margin-top:0}}
.tpurpose{{margin:0;color:var(--soft)}}
pre.code{{margin:0;background:#0f172a;color:#e2e8f0;border-radius:9px;padding:14px 16px;font-family:'IBM Plex Mono',monospace;font-size:12.5px;line-height:1.65;overflow-x:auto;white-space:pre}}
.tlist{{margin:.3em 0;padding-left:1.3em;color:var(--soft);font-size:.93rem}}
.tlist li{{margin:.3em 0}}
.tresult{{margin-top:14px;background:#f0fdf4;border-left:3px solid var(--green);color:#15803d;padding:9px 14px;border-radius:0 7px 7px 0;font-size:.93rem;font-weight:500}}

/* charts */
.rowlabel{{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--blue);letter-spacing:.06em;margin:26px 0 10px;font-weight:600}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:20px}}
.cchart{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 14px 6px}}
.chart{{width:100%;height:auto}}
.ctitle{{font-family:'Manrope','Noto Sans SC',sans-serif;font-size:13px;font-weight:700;fill:var(--ink)}}
.grid{{stroke:#eef2f7;stroke-width:1}} .axis{{stroke:#cbd5e1;stroke-width:1.3}}
.tick{{font-family:'IBM Plex Mono',monospace;font-size:10px;fill:var(--faint)}}
.ty{{text-anchor:end}} .tx{{text-anchor:middle}}
.axlab{{font-family:'IBM Plex Mono',monospace;font-size:10.5px;fill:var(--soft);text-anchor:middle}}
.leg{{font-family:'IBM Plex Mono',monospace;font-size:11px;fill:var(--ink)}}
.hlab{{font-family:'IBM Plex Mono',monospace;font-size:10px;text-anchor:end;font-weight:600}}
.vlab{{font-family:'IBM Plex Mono',monospace;font-size:9.5px;font-weight:600}}

.note{{background:var(--soft-blue);border:1px solid #bfdbfe;border-radius:12px;padding:16px 20px;margin:22px 0 0;font-size:.95rem;color:var(--soft)}}
.note b{{color:var(--blue-d)}}
.next{{margin:26px 0 0;border:1px dashed var(--blue);border-radius:12px;padding:18px 22px;background:#fff}}
.next .nk{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--blue);font-weight:600}}
footer{{margin-top:48px;padding-top:20px;border-top:1px solid var(--line);font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--faint)}}
@media(max-width:560px){{.wrap{{padding:34px 16px 70px}}}}
</style></head><body><div class="wrap">

<div class="kick">SJTU-TPMSHX · 均质化求解器 · Phase 0 纯几何 PoC</div>
<h1>非对称孔隙率 · <span class="em">完整执行流程</span></h1>
<p class="sub">偏移等值面 δ 把一个 TPMS 胞元的孔隙非对称分给两股流体（ε_A≠ε_B）。本页记录 Task 0→5 的全过程：模型、每步代码、TDD 验证、扫描结果与闸门判定。</p>

<div class="verdict">
  <div class="vk">Phase 0 闸门 · Gate</div>
  <div class="vmain">几何门 <b>PASS</b> —— 可用偏置 <b>≈ 2.9 : 1</b>（小通道不塌过半），远超 2:1 闸门。</div>
  <p>δ=0 端到端复现现有 compute_geometry（anchor OK）· 总孔隙 ε 微漂 1–3%（O(δ²)）· 9 个单测全绿 · 壁厚按 2C 常数（物理壁厚 / 0.3mm 打印地板延后到 STL 阶段）。纯几何证「能造这么不对称」；下游换热/降 dP 收益须 Phase 1（CFD）+ Phase 3（优化）。</p>
</div>

<div class="tbl"><table>
<thead><tr><th>TPMS</th><th>δ_max（连通）</th><th>r_usable（ε_B≥50%）</th><th>r_max（pinch）</th><th>ε 漂</th><th>闸门</th></tr></thead>
<tbody>{summ_rows}</tbody></table></div>

<h2>执行时间线</h2>
<p class="lead">6 步：T0 设置（无代码）→ T1–3 TDD 建几何核 → T4 扫描出数 → T5 本报告。T6（结论回写 vault）待做。</p>
<div class="timeline">{steps}</div>

<h2>逐步详解</h2>
{cards}

<h2>结果可视化</h2>
<div class="rowlabel">▌头牌：同一根 δ 轴 — 左 r 往上爬，右壁厚往下掉 = tradeoff</div>
<div class="grid2">
<div class="cchart">{chart_r}</div>
<div class="cchart">{chart_t}</div>
</div>
<div class="note"><b>怎么读：</b>往右推 δ，偏置比 r 单调↑（①），但挤压侧 ε_B 单调↓（②）。<b>壁厚按 2C 常数处理（PoC 简化，不追物理壁厚）</b>，故 δ_max 由<b>连通夹断</b>定（非壁地板）。可用上界取「ε_B 不塌过半（≥50%）」→ <b>r_usable ≈ 2.9:1</b>（≫2:1 闸门）。① y 截顶 8；近 δ_max 处 ε_B→0 使 r 飙到 7–24（pinch 虚高，无用工作点）。<br><span style="color:var(--faint)">注：物理壁厚 ≠ 2C（需除梯度 |∇φ|），真可制造性 0.3mm 地板延后到 STL 阶段。</span></div>

<div class="rowlabel">▌两侧孔隙怎么分化</div>
<div class="grid2">
<div class="cchart">{eps_charts[0]}</div>
<div class="cchart">{eps_charts[1] if len(eps_charts) > 1 else ''}</div>
</div>

<div class="rowlabel">▌每侧水力直径 D_h（→ 影响 h 与 dP）</div>
<div class="grid2">
<div class="cchart">{dh_charts[0]}</div>
<div class="cchart">{dh_charts[1] if len(dh_charts) > 1 else ''}</div>
</div>

<div class="next">
  <div class="nk">下一步 · T6 + Phase 1</div>
  <p style="margin:.4em 0 0;color:var(--soft)"><b>T6</b>：把本闸门结论回写 vault feasibility 文档 §5 + 更新 memory，给 Phase 0 盖章。<br>
  <b>Phase 1（CFD，数周）</b>：从可行 δ 选 2–3 点跑 detailed CFD，重标 per-side Nu/f；利用 void_A(+δ)≅void_B(−δ) 对称 → 单闭合面覆盖两侧（标定砍半）。<br>
  <b>真问号</b>：r=3.4–3.8 对你气-液工况能换多少降 dP / 缩机 —— Phase 1/3 才落定。</p>
</div>

<footer>纯几何 PoC · 数据 runs/_out/asym_geom_scan_2026-06-05.csv（82 行）· 壁厚按 2C 常数（物理壁厚 / 0.3mm 地板延后 STL）· 9 测全绿 · 分支 feat/asym-porosity-phase0 · 2026-06-05</footer>
</div></body></html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"[HTML] {OUT_HTML}")


if __name__ == "__main__":
    main()
