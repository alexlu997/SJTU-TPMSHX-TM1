"""10kW air-water 空冷器预测定尺 (一次性脚本, 非 production)。
空气热侧 (加压, 绝压), 水冷侧 (38C, 4 t/h)。3 工况, 一台机满足全部。
方形: 自由 s×s, 放开 450 包络。矩形 (后续): H=750 固定, 宽自由。
"""
from __future__ import annotations
import sys, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math
# 预测模式: 放开 450mm AM 包络。必须在 import design.sizing 之前设环境变量 ——
# sizing.py 在 import 时读取，spawn 出的 loky 子进程继承本进程 env → 子进程重新
# import 时也读到放开值。旧的 `SZ.S_MAX=2.0` 模块全局突变不传给子进程 (r2-runs-01)。
os.environ["TPMSHX_BUILD_S_MAX"] = "2.0"
os.environ["TPMSHX_BUILD_LX_MAX"] = "2.0"
import sjtu_tpmshx.design.sizing as SZ
from sjtu_tpmshx.design.cases import DesignCase
from sjtu_tpmshx.design.sizing import size_fixed_cell, solve_Lx, Design
from sjtu_tpmshx.design.select import enumerate_select, pareto_tags
from sjtu_tpmshx.design.forward import forward, dP_fracs
from sjtu_tpmshx.models.design_fluids import nu_re_window
from sjtu_tpmshx.design.report import cid, detail_rows
from sjtu_tpmshx.models.tpms_calc import geometry as _geom
import pandas as pd

try:                                   # GBK console 无法编码 ²/中文 → 强制 UTF-8 stdout
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(os.environ.get("TPMSHX_TOOL_OUT_DIR", ROOT / ".cache" / "aircooler-10kw"))
XLSX_OUT = str(OUT_DIR / "quick_design_result.xlsx")
HTML_OUT = str(OUT_DIR / "quick_design_aircooler_report.html")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_aircooler_runs.pkl")

AREA2 = 0.075        # 解读2: 总迎风面积 [m²] = 750 cm² (方形边 = sqrt = 273.9mm)
DP_DEGEN = 0.30      # dP frac > 此 → 退化标记 (同 sizing.DP_DEGEN_FRAC)

K = 273.15
AIR_DP_PA = 300.0       # 气侧许用压降 [Pa] (风机静压预算) → 钉住迎风面
# (T_in_C, P_kPa_abs, mdot_air, dT=T_in-45)  air cooled to 45C, water 38C/4t·h
ROWS = [(71.0, 145.0, 0.381), (65.6, 182.0, 0.483), (60.3, 242.0, 0.647)]

def build_cases(dp_frac=None):
    """dp_frac: 两侧许用压损 = dp_frac × 进口绝压 (如 0.05/0.10); None → 旧默认
    (气侧 300Pa, 水侧松 1.0)。"""
    cs = []
    for i, (Tin, Pk, m) in enumerate(ROWS, 1):
        P_h = Pk * 1e3
        if dp_frac is None:
            dlh, dlc = AIR_DP_PA / P_h, 1.0
        else:
            dlh = dlc = dp_frac
        cs.append(DesignCase(
            case=i, hot_fluid="air", T_in_h=Tin + K, P_in_h=P_h, mdot_h=m,
            cold_fluid="water", T_in_c=38.0 + K, P_in_c=1.0e6, mdot_c=1.111,
            Q=10_000.0, dPlim_h=dlh, dPlim_c=dlc,
            dT=Tin - 45.0))                                      # dT → 目标出风45
    return cs

H_RECT = 0.750          # 矩形迎风固定高 [m]

def show(d, tag, height=None):
    print(f"\n[{tag}] feasible={d.feasible} reason={d.reason!r}")
    if not d.feasible:
        return
    if height is None:
        dim = f"s={d.s*1e3:.1f}×{d.s*1e3:.1f}mm Lx={d.Lx*1e3:.1f}mm (方形)"
    else:
        dim = f"W={d.s*1e3:.1f}×H={height*1e3:.0f}mm Lx={d.Lx*1e3:.1f}mm (矩形)"
    print(f"  cell={d.topo} l={d.l} t={d.t}  {dim}  "
          f"V={d.V*1e3:.3f}L wt={d.weight:.3f}kg")
    print(f"  dP_hot_max={d.dP_hot_max*100:.2f}%  dP_cold_max={d.dP_cold_max*100:.2f}%  "
          f"T_out_hot_max={d.T_out_hot_max-K:.2f}C")
    for pc in d.percase:
        print(f"   case{pc['case']}: T_air_out={pc['T_air_out']-K:.2f}C "
              f"T_w_out={pc['T_cold_out']-K:.2f}C Q={pc['Q_W']:.0f}W "
              f"dPh={pc['dP_hot_pa']:.1f}Pa dPc={pc['dP_cold_pa']:.1f}Pa "
              f"Re_h={pc['Re_hot']:.0f} Re_c={pc['Re_cold']:.0f}")

def size_fixed_area(cases, topo, l, t, A_f, arr="cross", k_s=16.0,
                    prop_model="mean", rho_s=7900.0):
    """解读2: 迎风总面积固定 = A_f (方形, 边=sqrt(A_f)), 仅深度 Lx 自由。
    面积固定 → 不能放大迎风降气阻。Lx = max(冷却所需, 满足水侧 dP 所需);
    叉流水侧 dP 随 Lx↓ (迎风 Lx·s 变大) → 加厚降水阻, 但气阻随 Lx↑。
    feasible = 冷却可达 + 两侧 dP ≤ 各自上限 (Lx≤cap)。"""
    s = math.sqrt(A_f)
    geo = _geom(topo, l, t, k_s, N=128); EPS = geo["epsilon"]
    Lx_cool, seed = 0.0, None                  # 全 K 冷却 Lx (固定 s)
    for c in cases:
        lx, r = solve_Lx(c, topo, l, t, s, arr, k_s=k_s, prop_model=prop_model, seed=seed)
        if lx is None:
            return Design(False, topo, l, t, s, arrangement=arr,
                          reason="冷却不可达@固定面积")
        if r is not None:
            seed = r.fields
        Lx_cool = max(Lx_cool, lx)
    if Lx_cool > SZ.LX_MAX:
        return Design(False, topo, l, t, s, arrangement=arr, reason="Lx>cap@固定面积")
    # 加厚 Lx 至满足全 K 水侧 dP ≤ 上限 (叉流水阻随 Lx↓); 升序扫首达标点
    Lx = Lx_cool
    if arr == "cross":
        for i in range(41):
            Lxi = Lx_cool + (SZ.LX_MAX - Lx_cool) * i / 40
            if all(dP_fracs(c, topo, l, t, s, Lxi, arr)[1] <= c.dPlim_c for c in cases):
                Lx = Lxi; break
        else:
            Lx = SZ.LX_MAX                     # 水阻在 cap 内永不达标 → 终验标不可行
    percase, dPh, dPc, Tout = [], 0.0, 0.0, 0.0
    re_h = re_c = 0.0; warns = set()
    for c in cases:
        r = forward(c, topo, l, t, s, Lx, arr, k_s=k_s, prop_model=prop_model)
        percase.append(dict(
            case=c.case, hot_fluid=c.hot_fluid, cold_fluid=c.cold_fluid,
            T_air_out=r.T_out_hot, T_cold_out=r.T_out_cold, Q_W=r.Q_hot,
            dP_hot_frac=r.dP_hot_frac, dP_hot_pa=r.dP_hot_frac * c.P_in_h,
            dP_cold_frac=r.dP_cold_frac, dP_cold_pa=r.dP_cold_frac * c.P_in_c,
            Re_hot=r.Re_hot, Re_cold=r.Re_cold))
        dPh = max(dPh, r.dP_hot_frac); dPc = max(dPc, r.dP_cold_frac)
        Tout = max(Tout, r.T_out_hot)
        re_h = max(re_h, r.Re_hot); re_c = max(re_c, r.Re_cold)
        hlo, hhi = nu_re_window(c.hot_fluid); clo, chi = nu_re_window(c.cold_fluid)
        if r.Re_hot < hlo: warns.add("热Re↓外推")
        if r.Re_hot > hhi: warns.add("热Re↑外推")
        if r.Re_cold < clo: warns.add("冷Re↓外推")
        if r.Re_cold > chi: warns.add("冷Re↑外推")
        if r.dP_hot_frac > c.dPlim_h: warns.add("气dP>限")        # 面积固定, 气阻随 Lx 增
        if r.dP_cold_frac > c.dPlim_c: warns.add("水dP>限")       # 加厚到 cap 仍超 → 面积太小
        if r.dP_hot_frac > DP_DEGEN: warns.add("热dP退化")
        if r.dP_cold_frac > DP_DEGEN: warns.add("冷dP退化")
    # FIX (2026-06-24 audit): check EACH case against its OWN dP ceiling, not
    # cases[0]'s. dPh/dPc are max-over-cases; with build_cases(dp_frac=None) the
    # per-case dPlim differ (dlh=AIR_DP_PA/P_h varies with P_h), so a higher-
    # pressure case could exceed its own tighter limit yet pass the cases[0] gate.
    # Mirrors the per-case thickening loop (line 106) and design.sizing._maxnorm_dP.
    hot_ok = all(pc['dP_hot_frac'] <= c.dPlim_h + 1e-9
                 for pc, c in zip(percase, cases))
    cold_ok = all(pc['dP_cold_frac'] <= c.dPlim_c + 1e-9
                  for pc, c in zip(percase, cases))
    dp_ok = hot_ok and cold_ok
    feasible = dp_ok and Lx <= SZ.LX_MAX
    reason = "" if feasible else ("气dP>限@面积" if not hot_ok else "水dP>限@面积")
    V = A_f * Lx
    return Design(feasible, topo, l, t, s, Lx, arr, V, (1.0 - EPS) * V * rho_s,
                  dPh, dPc, Tout, reason=reason, percase=percase, height=0.0,
                  Re_hot_max=re_h, Re_cold_max=re_c, validity=";".join(sorted(warns)))

def enumerate_area(cases, A_f, arr="cross", prop_model="mean", n_jobs=-1):
    """解读2 枚举: 全 NODES 各跑 size_fixed_area, 取 min-V best。
    size_fixed_area 为本模块顶层函数 → loky 可 pickle 并行 (各 worker 重 import 模块)。"""
    from sjtu_tpmshx.design.select import NODES
    combos = [(tp, l, t) for tp in NODES["topo"] for l in NODES["l"] for t in NODES["t"]]
    if n_jobs == 1:
        results = [size_fixed_area(cases, tp, l, t, A_f, arr, prop_model=prop_model)
                   for tp, l, t in combos]
    else:
        from joblib import Parallel, delayed
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(size_fixed_area)(cases, tp, l, t, A_f, arr, prop_model=prop_model)
            for tp, l, t in combos)
    feas = [d for d in results if d.feasible]
    best = min(feas, key=lambda d: d.V) if feas else None
    return results, best

def _summary_rows(results, height):
    """复刻 report.summary_rows, 但矩形 (height!=None) 的 H_mm 取固定高 (而非 W)。"""
    tags = pareto_tags(results)
    H_fix = None if height is None else round(height * 1e3, 2)
    out = []
    for d in results:
        Hmm = H_fix if (height is not None and d.feasible) else round(d.s * 1e3, 2)
        out.append(dict(
            构型=cid(d), 拓扑=d.topo, l_mm=d.l, t_mm=d.t, 布置=d.arrangement,
            可行=("是" if d.feasible else "否"),
            W_mm=round(d.s * 1e3, 2), H_mm=Hmm, Lx_mm=round(d.Lx * 1e3, 2),
            V_L=round(d.V * 1e3, 4), 重量_kg=round(d.weight, 4),
            dP热_max=round(d.dP_hot_max, 4), dP冷_max=round(d.dP_cold_max, 4),
            各case气dP_pct=("/".join(f"{p['dP_hot_frac']*100:.2f}" for p in d.percase)
                           if d.percase else ""),
            各case水dP_pct=("/".join(f"{p['dP_cold_frac']*100:.2f}" for p in d.percase)
                           if d.percase else ""),
            备注=d.reason, 标记=",".join(tags.get(id(d), []))))
    return out

def _sorted_summary(results, height):
    df = pd.DataFrame(_summary_rows(results, height))
    if not df.empty:
        df = df.sort_values(["可行", "V_L"], ascending=[True, True])
    return df

def write_xlsx_sweep(path, runs):
    """runs = [(key, label, results, height), ...] → 每 run 2 sheet (汇总/明细)。
    列同 report.write_xlsx (含 Re/验证域)。"""
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for key, _label, res, h in runs:
            _sorted_summary(res, h).to_excel(xw, sheet_name=f"{key}-汇总", index=False)
            pd.DataFrame(detail_rows(res) or [{"提示": "无可行"}]).to_excel(
                xw, sheet_name=f"{key}-明细", index=False)
    print(f"[xlsx] {path}")

def _best(results):
    feas = [d for d in results if d.feasible]
    return min(feas, key=lambda d: d.V) if feas else None

def _lowdp(results):
    feas = [d for d in results if d.feasible]
    return min(feas, key=lambda d: d.dP_cold_max) if feas else None

def write_html_sweep(path, runs, A_f, arr="cross"):
    """runs = [(key, label, results, height), ...]. 气水压损 5%/10% 两档 × 两解读。"""
    K0 = 273.15
    side = math.sqrt(A_f) * 1e3        # 解读2 方形边 [mm]
    arr_label = "逆流 (counter)" if arr == "counter" else "叉流 (cross)"
    flow_desc = ("逆流 (空气 +x / 水 −x 同轴反向): 两股共用迎风面 + 流程 Lx, 两侧 dP 均随 Lx↑; "
                 "水侧 dP 只取决于迎风总面积 + Lx (无叉流的朝向/流程不对称)"
                 if arr == "counter"
                 else "叉流 (空气 +x / 水 +y): 水沿一条迎风边流, 水侧 dP 受朝向/流程影响")
    interp2_note = ("面积锁死, 仅深度自由。逆流两侧 dP 均随 Lx↑ → 不能靠加厚降水阻; "
                    "冷却所需 Lx 处若 dP 超限即不可行。"
                    if arr == "counter"
                    else "面积锁死, 仅深度自由 (叉流可加厚降水阻)。")
    stack_note = ("逆流 nz=2, z 向分段需重验"
                  if arr == "counter" else "叉流 z 均匀, 性能线性可拆")
    def cells(d, h):
        if d is None:
            return ("—",) * 8
        dim = (f"{d.s*1e3:.0f}×{d.s*1e3:.0f}×{d.Lx*1e3:.1f}" if h is None
               else f"{d.s*1e3:.0f}×{h*1e3:.0f}×{d.Lx*1e3:.1f}")
        air_dp = max(pc["dP_hot_pa"] for pc in d.percase)
        wat_dp = max(pc["dP_cold_pa"] for pc in d.percase) / 1e3
        flag = getattr(d, "validity", "") or "—"
        return (f"{d.topo} l{d.l:g}/t{d.t:g}", dim, f"{d.V*1e3:.2f}",
                f"{d.weight:.1f}", f"{air_dp:.0f}", f"{wat_dp:.1f}",
                f"{d.T_out_hot_max-K0:.1f}", flag)
    def tbl(results, h, title):
        df = _sorted_summary(results, h)
        head = "".join(f"<th>{c}</th>" for c in df.columns)
        body = ""
        for _, r in df.iterrows():
            tds = "".join(f"<td>{('' if v is None else v)}</td>" for v in r)
            cls = ' class="feas"' if r["可行"] == "是" else ' class="infeas"'
            body += f"<tr{cls}>{tds}</tr>"
        return f"<h3>{title}</h3><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    cmp_rows = ""
    for _key, label, res, h in runs:
        c = cells(_best(res), h)
        cmp_rows += "<tr><td>" + label + "</td>" + "".join(f"<td>{x}</td>" for x in c) + "</tr>"
    full_tbls = "".join(tbl(res, h, label) for _key, label, res, h in runs)
    # 各 min-V 件的逐工况压损明细
    pc_secs = ""
    for _key, label, res, _h in runs:
        d = _best(res)
        if d is None:
            continue
        rows = ""
        for pc in d.percase:
            rows += (f"<tr><td>{pc['case']}</td><td>{pc['T_air_out']-K0:.1f}</td>"
                     f"<td><b>{pc['dP_hot_frac']*100:.2f}</b></td><td>{pc['dP_hot_pa']:.0f}</td>"
                     f"<td><b>{pc['dP_cold_frac']*100:.2f}</b></td><td>{pc['dP_cold_pa']/1e3:.1f}</td>"
                     f"<td>{pc['Re_hot']:.0f}</td><td>{pc['Re_cold']:.0f}</td></tr>")
        pc_secs += (f"<h3>{label} — {d.topo} l{d.l:g}/t{d.t:g}</h3>"
                    f"<table><thead><tr><th>工况</th><th>出风 °C</th>"
                    f"<th>气dP %</th><th>气dP Pa</th><th>水dP %</th><th>水dP kPa</th>"
                    f"<th>Re气</th><th>Re水</th></tr></thead><tbody>{rows}</tbody></table>")
    case_rows = ""
    for c in CASES:
        case_rows += (f"<tr><td>{c.case}</td><td>{c.T_in_h-K0:.1f}</td>"
                      f"<td>{c.P_in_h/1e3:.0f}</td><td>{c.mdot_h:.3f}</td><td>45</td>"
                      f"<td>{c.T_in_c-K0:.0f}</td><td>{c.P_in_c/1e6:.1f}</td>"
                      f"<td>{c.mdot_c:.3f}</td><td>10.0</td></tr>")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>10kW 空冷器 TPMS 快速设计预测</title><style>
body{{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:1100px;
margin:24px auto;padding:0 18px;color:#1a1a1a;line-height:1.5}}
h1{{font-size:22px;border-bottom:3px solid #2c5aa0;padding-bottom:6px}}
h2{{font-size:17px;color:#2c5aa0;margin-top:28px}}h3{{font-size:14px;margin-top:18px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}}
th,td{{border:1px solid #ccc;padding:4px 7px;text-align:center}}
th{{background:#2c5aa0;color:#fff;font-weight:600}}
tr.infeas{{color:#999;background:#fafafa}}tr.feas:nth-child(even){{background:#f0f5fb}}
.note{{background:#fff8e6;border-left:4px solid #e0a800;padding:8px 12px;margin:10px 0;font-size:13px}}
.key{{background:#e8f4ea;border-left:4px solid #2e8b57;padding:8px 12px;margin:10px 0;font-size:13px}}
.warn{{background:#fdecea;border-left:4px solid #c0392b;padding:8px 12px;margin:10px 0;font-size:13px}}
code{{background:#eee;padding:1px 4px;border-radius:3px}}
caption{{font-size:11px;color:#666;caption-side:bottom;padding-top:4px}}
</style></head><body>
<h1>10kW 空冷器 — TPMS 换热器快速设计预测报告</h1>
<p style="color:#666;font-size:13px">生成 {time.strftime('%Y-%m-%d')} · SJTU-TPMSHX 快速设计模块 (LTNE {arr_label}, 均温物性) · 许用压损 5% / 10% × 迎风「750」两解读</p>
<p class="warn">历史研究模板：表格来自本次传入的计算或缓存；下文固定结论沿用 2026-06 报告，不代表当前 TM1 的设计或实验精度验收。重新选型前须核对工况、模型及原生结果状态。</p>

<h2>1. 设计工况 (空气热侧 → 冷却到 45°C, 水冷侧)</h2>
<table><thead><tr><th>工况</th><th>进风温 °C</th><th>空气绝压 kPa</th><th>空气 mdot kg/s</th>
<th>出风温 °C</th><th>进水温 °C</th><th>水绝压 MPa</th><th>水 mdot kg/s</th><th>散热 kW</th></tr></thead>
<tbody>{case_rows}</tbody><caption>进风温由 Q=10kW + 体积流量 0.25 m³/s(均温密度) + 出风45°C 反推; 一台机须同时满足全部工况。</caption></table>

<h2>2. 排列 + 压损设定 + 「750」两解读</h2>
<ul style="font-size:13px">
<li><b>排列 = {arr_label}</b>。{flow_desc}。</li>
<li><b>许用压损 = 进口绝压的 5% 与 10% 两档, 气水两侧同限</b> (替代旧 300Pa)。气侧 5%≈7–12kPa / 10%≈15–24kPa;
水侧 5%=50kPa / 10%=100kPa。放宽压损 → 设备更小。</li>
<li><b>解读1 一条边=750mm</b>: 矩形, 一边 750mm 固定, 另一边+深度自由, min-V。迎风可调 → 压损放宽直接缩体积。</li>
<li><b>解读2 总面积=750cm² (0.075m²)</b>: 方形 (边 {side:.0f}mm), {interp2_note}
面速 ≈ {0.25/A_f:.1f} m/s 固定。</li>
</ul>

<h2>3. 推荐结果对比 (各 min-V)</h2>
<table><thead><tr><th>方案 (压损上限)</th><th>胞元</th><th>尺寸 W×H×Lx mm</th><th>体积 L</th>
<th>重量 kg</th><th>气侧 dP Pa</th><th>水侧 dP kPa</th><th>出风温 °C</th><th>验证/标记</th></tr></thead>
<tbody>{cmp_rows}</tbody><caption>dP 为全工况最大值; — = 无可行件。</caption></table>
<div class="key"><b>看点:</b> 解读1 体积随压损 5%→10% 明显下降 (迎风缩小)。解读2 体积基本不随压损变 (迎风面积锁死), 只能靠加厚/换胞元满足水侧 dP。</div>

<h2>3b. 各工况压损明细 (各 min-V 件)</h2>
<p style="font-size:12px;color:#666">每件按 3 个工况逐一列出气/水侧相对压损 %(占各自进口绝压)与绝对值。汇总表为全工况最大值; 此处见各 case 具体数。</p>
{pc_secs}

<h2>4. 全枚举 (各 40 构型, 含 各case气/水dP% 列)</h2>
{full_tbls}

<h2>5. 注意事项 (Caveats)</h2>
<div class="note"><ul style="margin:0">
<li><b>许用压损 5–10% 偏高</b>: 气侧 5–10% = 7–24 kPa, 需高静压鼓风机 (非普通轴流风扇); 加压回路下可接受。</li>
<li><b>「750」单位/含义为假设</b>: 解读2 按 750 cm²=0.075 m²。若实为他值, 数全变 — 须甲方确认。</li>
<li><b>气侧 Nu 低 Re 外推</b>: 大迎风时气 Re 偏低, 部分近/低于拟合窗 [400,16000] 下沿; 见各行「验证域」。</li>
<li><b>水侧 Nu</b>: nu_water_topo per-topology 直拟合 (Diamond/Gyroid 各自), 域 100-50000 (气侧控阻, 影响小)。</li>
<li><b>dP = D-F 芯体预测</b>, ~几十% 不确定度, <b>不含进出口集管/风口损失</b> (实物另加)。</li>
<li><b>制造</b>: 超 450mm AM 包络须分段堆叠 ({stack_note}); 进风温/空气压力为反推/假设值。</li>
</ul></div>

<h2>6. 产物</h2>
<ul style="font-size:13px">
<li>枚举结果 Excel: <code>{XLSX_OUT}</code> (4 组 = 2 解读 × 5%/10%, 各汇总/明细)</li>
<li>工况入口: <code>projects/704-Aircooler-10kW/predict_aircooler_10kw.py</code> 的 <code>build_cases()</code>；本脚本不读取外部工况 Excel。</li>
</ul>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[html] {path}")

XLSX_RPT = str(OUT_DIR / "quick_design_aircooler_汇报.xlsx")
HTML_RPT = str(OUT_DIR / "quick_design_aircooler_汇报.html")

# 术语速查 (给非专业听众的人话解释)
GLOSSARY = [
    ("TPMS 换热器", "用金属 3D 打印做出的、像「连续曲面海绵」的换热芯;曲面把冷热流体分开,换热面积极大且自重轻。"),
    ("Diamond / Gyroid", "两种 TPMS 曲面「花纹」(类似不同的编织纹路),换热与阻力特性略不同。"),
    ("晶胞尺寸 l (mm)", "曲面花纹的「重复单元」边长;越小越密 → 换热强但阻力大。"),
    ("壁厚 t (mm)", "曲面金属壁的厚度。"),
    ("迎风面 (宽 × 高)", "流体正对吹入的那个面的尺寸;越大流速越低、阻力越小,但占地大。"),
    ("芯体深度 Lx (mm)", "流体穿过换热芯走过的距离(芯有多「厚」)。"),
    ("体积 (L)", "换热芯的体积,越小越紧凑(本设计追求体积最小 = min-V)。"),
    ("叉流 / 逆流", "空气与水的相对流向:叉流 = 垂直交叉;逆流 = 正对反向。逆流换热效率更高。"),
    ("压损 / 压降 (%)", "流体穿过芯体损失的压力,占进口压力的百分比;越大越费风机(气)/水泵(水)。"),
    ("出风温 (°C)", "空气被冷却后的出口温度,要求 ≤ 45°C。"),
    ("验证域 / 外推", "经验换热公式有适用范围;超出范围的预测可信度下降(报告会标注)。"),
]

def _ht_area(d):
    """单股换热面积 [m²] = 面积密度 A_0 [m²/m³] × 芯体体积。
    两股流体由同一 TPMS 分隔曲面隔开、各接触一侧 → 气侧 = 水侧(同一面)。"""
    return _geom(d.topo, d.l, d.t, 16.0, N=128)["A_0"] * d.V

def _ov_rows(flow, runs):
    """从一个流向的 4 个 run 各取 min-V → 对比总览行。"""
    K0 = 273.15
    out = []
    for key, _label, res, h in runs:
        cap = key.split("_")[1]
        d = _best(res)
        if d is None:
            out.append({"流动布置": flow, "许用压降上限": cap, "推荐构型": "无可行方案"})
            continue
        Hmm = (h if h else d.s) * 1e3
        out.append({
            "流动布置": flow, "许用压降上限": cap,
            "推荐构型": f"{d.topo} l{d.l:g}/t{d.t:g}",
            "迎风宽_mm": round(d.s * 1e3, 1), "迎风高_mm": round(Hmm, 1),
            "芯体深度_mm": round(d.Lx * 1e3, 1),
            "体积_L": round(d.V * 1e3, 3), "重量_kg": round(d.weight, 2),
            "单股换热面积_m²": round(_ht_area(d), 3),
            "出风温_°C": round(d.T_out_hot_max - K0, 1),
            "气侧压降_各工况%": "/".join(f"{p['dP_hot_frac']*100:.1f}" for p in d.percase),
            "水侧压降_各工况%": "/".join(f"{p['dP_cold_frac']*100:.2f}" for p in d.percase),
        })
    return out

def write_combined_xlsx(path, cross_runs, counter_runs):
    """汇报版: 说明_术语 + 对比总览(叉流+逆流各 min-V) + 各流向枚举汇总。"""
    ov = _ov_rows("叉流", cross_runs) + _ov_rows("逆流", counter_runs)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(ov).to_excel(xw, sheet_name="对比总览(各min-V)", index=False)
        for flow, runs in [("叉流", cross_runs), ("逆流", counter_runs)]:
            for key, _label, res, h in runs:
                pre = ("叉" if flow == "叉流" else "逆") + key      # 叉解读1_5% ≤31 char
                _sorted_summary(res, h).to_excel(xw, sheet_name=f"{pre}", index=False)
    print(f"[xlsx 汇报] {path}")

_ARROW_DEFS = ('<defs>'
    '<marker id="ar" markerWidth="9" markerHeight="9" refX="6.5" refY="3" orient="auto">'
    '<path d="M0,0 L7,3 L0,6 Z" fill="context-stroke"/></marker>'
    '<marker id="aR" markerWidth="9" markerHeight="9" refX="6.5" refY="3" orient="auto">'
    '<path d="M0,0 L7,3 L0,6 Z" fill="#c0392b"/></marker>'
    '<marker id="aB" markerWidth="9" markerHeight="9" refX="6.5" refY="3" orient="auto">'
    '<path d="M0,0 L7,3 L0,6 Z" fill="#2563eb"/></marker></defs>')

_SVG_CROSS = (
    '<svg viewBox="0 0 300 200" width="100%" style="max-width:300px">' + _ARROW_DEFS +
    '<rect x="98" y="64" width="104" height="72" rx="7" fill="#ece6da" stroke="#8a8170"/>'
    '<text x="150" y="104" text-anchor="middle" font-size="11" fill="#5b6573">TPMS 芯体</text>'
    # 空气 水平 →
    '<line x1="16" y1="100" x2="92" y2="100" stroke="#c0392b" stroke-width="3" marker-end="url(#aR)"/>'
    '<line x1="206" y1="100" x2="286" y2="100" stroke="#c0392b" stroke-width="3" marker-end="url(#aR)"/>'
    '<text x="16" y="90" font-size="10.5" fill="#c0392b">空气 ~70°C</text>'
    '<text x="240" y="90" font-size="10.5" fill="#c0392b">→ 45°C</text>'
    # 水 竖直 ↑
    '<line x1="150" y1="190" x2="150" y2="142" stroke="#2563eb" stroke-width="3" marker-end="url(#aB)"/>'
    '<line x1="150" y1="60" x2="150" y2="14" stroke="#2563eb" stroke-width="3" marker-end="url(#aB)"/>'
    '<text x="156" y="184" font-size="10.5" fill="#2563eb">水 38°C</text>'
    '<text x="156" y="28" font-size="10.5" fill="#2563eb">~40°C</text>'
    '</svg>')

_SVG_COUNTER = (
    '<svg viewBox="0 0 300 200" width="100%" style="max-width:300px">' + _ARROW_DEFS +
    '<rect x="98" y="64" width="104" height="72" rx="7" fill="#ece6da" stroke="#8a8170"/>'
    '<text x="150" y="104" text-anchor="middle" font-size="11" fill="#5b6573">TPMS 芯体</text>'
    # 空气 上半 左→右
    '<line x1="16" y1="86" x2="92" y2="86" stroke="#c0392b" stroke-width="3" marker-end="url(#aR)"/>'
    '<line x1="206" y1="86" x2="286" y2="86" stroke="#c0392b" stroke-width="3" marker-end="url(#aR)"/>'
    '<text x="16" y="78" font-size="10.5" fill="#c0392b">空气 ~70°C</text>'
    '<text x="242" y="78" font-size="10.5" fill="#c0392b">→ 45°C</text>'
    # 水 下半 右→左
    '<line x1="286" y1="116" x2="210" y2="116" stroke="#2563eb" stroke-width="3" marker-end="url(#aB)"/>'
    '<line x1="92" y1="116" x2="16" y2="116" stroke="#2563eb" stroke-width="3" marker-end="url(#aB)"/>'
    '<text x="232" y="132" font-size="10.5" fill="#2563eb">水 38°C</text>'
    '<text x="16" y="132" font-size="10.5" fill="#2563eb">~40°C</text>'
    '</svg>')

FLOW_FIG = (
    '<div style="display:flex;gap:16px;flex-wrap:wrap;margin:6px 0 14px">'
    '<div class="card" style="flex:1;min-width:270px;text-align:center;margin:0">'
    '<div style="font-weight:700;color:#13303a">叉流 (cross-flow)</div>' + _SVG_CROSS +
    '<div class="legend">空气与水<b>垂直交叉</b>;水沿一条迎风边横穿。'
    '本例边=750mm → 水流程短、过流截面大 → <b style="color:#15803d">水侧压降低</b>(0.18–0.27%)</div></div>'
    '<div class="card" style="flex:1;min-width:270px;text-align:center;margin:0">'
    '<div style="font-weight:700;color:#13303a">逆流 (counter-flow)</div>' + _SVG_COUNTER +
    '<div class="legend">空气与水<b>同轴反向</b>;水穿过整个迎风面、流速低 → '
    '<b style="color:#15803d">水侧压降极低</b>,且对数平均温差更大、换热更高效</div></div>'
    '</div>')

_REQ = '<span class="bd req">甲方要求</span>'
_INF = '<span class="bd inf">我们推测</span>'

# 数据来源标注: (参数, 取值, 徽章, 说明)
_SRC = [
    ("散热量", "10 kW", _REQ, "图纸给定"),
    ("空气流量", "约 0.25 m³/s", _REQ, "图纸给定(体积流量)"),
    ("出风温度", "≤ 45 °C", _REQ, "图纸给定"),
    ("进水温度", "≤ 38 °C", _REQ, "图纸给定"),
    ("冷却水量", "≤ 4 t/h", _REQ, "图纸给定"),
    ("迎风面", "一边 750 mm × 高度", _REQ, "图纸给定;750 = 单边边长(甲方确认),另一边自由"),
    ("冷却水侧设计压力", "1.0 MPa", _REQ, "图纸给定(结构承压,非流动压降)"),
    ("进风温度", "约 60–71 °C", _INF, "由 散热10kW + 空气流量 + 出风45°C 反推"),
    ("空气压力", "0.145–0.242 MPa", _INF, "工况草稿假设值;图纸未给空气压力"),
    ("空气质量流量", "0.38–0.65 kg/s", _INF, "= 0.25 m³/s × 均温空气密度(派生)"),
    ("出水温度 / 水温差", "约 40 °C / 2 K", _INF, "由 散热10kW + 冷却水量 反算"),
    ("许用压降(气/水)", "5% 与 10% 两档", _INF, "我们设定;图纸无气侧压降要求"),
    ("芯体材料", "304 不锈钢", _INF, "默认假设(可换铝 / 铜)"),
    ("材料密度 ρ", "7900 kg/m³", _INF, "用于<b>重量</b> = (1−ε)·体积·ρ(ε=孔隙率)"),
    ("材料热导率 k", "16 W/(m·K)", _INF, "用于<b>固体导热</b>(LTNE);钢导热低,对换热影响小"),
    ("物性取值", "进出口平均温度", _INF, "建模选择"),
    ("流动布置", "叉流 / 逆流", _INF, "我们对比探索"),
    ("TPMS 拓扑 / 晶胞", "Diamond+Gyroid × l,t 枚举", _INF, "我们的设计自由度"),
]

def _spec_block():
    rows = "".join(
        f"<tr><td>{p}</td><td>{v}</td><td class='src'>{b}</td>"
        f"<td style='font-size:12px;color:#5b6573'>{n}</td></tr>"
        for p, v, b, n in _SRC)
    return (
        '<h3>甲方原始技术要求(图纸原文)</h3>'
        '<div class="card" style="margin-top:6px"><table style="margin:0">'
        '<thead><tr><th>项目</th><th>要求值</th></tr></thead><tbody>'
        '<tr><td>单台散热量</td><td>10 KW</td></tr>'
        '<tr><td>单台空气流量</td><td>约 0.25 m³/s</td></tr>'
        '<tr><td>出风温度</td><td>≤ 45 °C</td></tr>'
        '<tr><td>进水温度</td><td>≤ 38 °C</td></tr>'
        '<tr><td>冷却水量</td><td>≤ 4 t/H</td></tr>'
        '<tr><td>迎风面积</td><td>750 × 高度</td></tr>'
        '<tr><td>冷却水侧设计压力</td><td>1.0 MPa</td></tr>'
        '</tbody></table></div>'
        '<h3>数据来源标注 — <span class="bd req">甲方要求</span> 还是 '
        '<span class="bd inf">我们推测</span></h3>'
        '<p class="legend">汇报要点:绿色为甲方硬性要求,橙色为图纸未给、由我们反推或假设的参数(汇报时应说明)。</p>'
        '<table><thead><tr><th>参数</th><th>取值</th><th class="src">来源</th><th>说明</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>')

def write_combined_html(path, cross_runs, counter_runs, A_f):
    """汇报版 HTML: 结论先行 + 术语速查 + 需求 + 方法 + 叉流/逆流对比 + 注意事项。
    面向非专业听众, 术语全部人话解释。"""
    K0 = 273.15
    flows = [("叉流", cross_runs), ("逆流", counter_runs)]

    def comp_rows():
        body = ""
        for flow, runs in flows:
            rec = (flow == "逆流")
            for key, _label, res, h in runs:
                d = _best(res)
                cap = key.split("_")[1]
                cls = ' class="rec"' if rec else ""
                if d is None:
                    body += (f'<tr{cls}><td>{flow}</td><td>≤{cap}</td>'
                             f'<td colspan="8">无可行方案</td></tr>')
                    continue
                Hmm = (h if h else d.s) * 1e3
                gp = "/".join(f"{p['dP_hot_frac']*100:.1f}" for p in d.percase)
                wp = "/".join(f"{p['dP_cold_frac']*100:.2f}" for p in d.percase)
                body += (f'<tr{cls}><td>{flow}</td><td>≤{cap}</td>'
                         f'<td>{d.topo} l{d.l:g}/t{d.t:g}</td>'
                         f'<td>{d.s*1e3:.0f}×{Hmm:.0f}×{d.Lx*1e3:.0f}</td>'
                         f'<td class="num">{d.V*1e3:.2f}</td>'
                         f'<td class="num">{d.weight:.1f}</td>'
                         f'<td class="num">{_ht_area(d):.2f}</td>'
                         f'<td class="num">{gp}</td><td class="num">{wp}</td>'
                         f'<td class="num">{d.T_out_hot_max-K0:.1f}</td></tr>')
        return body

    case_rows = "".join(
        f"<tr><td>#{c.case}</td><td>{c.T_in_h-K0:.0f}→45</td><td>{c.P_in_h/1e3:.0f}</td>"
        f"<td>{c.mdot_h:.2f}</td><td>38→~40</td><td>{c.mdot_c:.2f}</td></tr>"
        for c in CASES)

    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>10 kW 空冷器 TPMS 换热芯方案预测</title><style>
:root{{--ink:#1f2933;--mut:#6b7682;--accent:#0f766e;--accent2:#0b5d57;
--soft:#eef6f4;--line:#e4e8ec;--bg:#eef1f3;--card:#fff;
--flag:#b46a00;--flagbg:#fbf4e9;--risk:#b3261e;--riskbg:#fbeeec}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.78;
font-family:"Microsoft YaHei","PingFang SC","Segoe UI",system-ui,sans-serif;
font-feature-settings:"tnum"}}
.wrap{{max-width:900px;margin:26px auto;background:var(--card);border-radius:12px;
overflow:hidden;box-shadow:0 4px 30px rgba(20,45,55,.10)}}
.head{{padding:36px 44px 26px;border-top:5px solid var(--accent);
background:linear-gradient(180deg,#f3faf8,#fff)}}
.org{{font-size:11.5px;letter-spacing:.22em;color:var(--accent);font-weight:600;
text-transform:uppercase;margin:0}}
h1{{font-size:26px;font-weight:700;line-height:1.3;margin:9px 0 6px;color:#143038}}
.sub{{font-size:12.5px;color:var(--mut);margin:0}}
.body{{padding:8px 34px 8px}}
.abstract{{font-size:14px;color:#32434b;margin:20px 0 16px;padding:15px 20px;
border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:8px;background:var(--soft);line-height:1.85}}
.abstract b{{color:var(--accent2)}}
.stats{{display:flex;flex-wrap:wrap;border:1px solid var(--line);
border-radius:10px;overflow:hidden;margin:0 0 6px;background:#fff}}
.stat{{flex:1;min-width:130px;padding:14px 18px;border-right:1px solid var(--line)}}
.stat:last-child{{border-right:none}}
.stat .v{{font-size:21px;font-weight:700;color:var(--accent)}}
.stat .l{{font-size:12px;color:var(--mut);margin-top:2px}}
h2{{font-size:18px;font-weight:700;margin:36px 0 12px;color:#143038;
display:flex;align-items:center;gap:10px}}
h2 .n{{display:inline-flex;align-items:center;justify-content:center;min-width:26px;
height:26px;padding:0 8px;background:var(--accent);color:#fff;border-radius:7px;
font-size:13px;font-weight:700}}
h3{{font-size:14.5px;font-weight:700;margin:20px 0 6px;color:#23424b}}
p,li{{font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:11.5px;margin:12px 0;
border:1px solid var(--line);border-radius:8px;overflow:hidden}}
thead th{{background:#e9f3f1;color:#13383c;padding:6px 7px;text-align:left;
font-weight:700;border-bottom:1px solid var(--line);white-space:nowrap;font-size:11.5px}}
tbody td{{border-bottom:1px solid #eef1f3;padding:6px 7px;text-align:left}}
tbody tr:last-child td{{border-bottom:none}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.src{{text-align:center}}
tr.rec td{{background:var(--soft)}}
.card{{border:1px solid var(--line);border-radius:9px;padding:15px 20px;
margin:13px 0;background:#fcfdfd}}
.note{{border-left:4px solid var(--accent);border-radius:0 8px 8px 0;
padding:11px 18px;margin:12px 0;font-size:13.5px;background:var(--soft);line-height:1.78}}
.note.flag{{border-left-color:var(--flag);background:var(--flagbg)}}
.note.risk{{border-left-color:var(--risk);background:var(--riskbg)}}
.tag{{font-weight:700;color:#143038}}
.legend{{font-size:11.5px;color:var(--mut);margin:6px 0 0;line-height:1.65}}
.mut{{color:var(--mut)}}
.bd{{font-size:11.5px;font-weight:600}}
.bd.req{{color:var(--accent)}}
.bd.inf{{color:var(--flag);font-style:italic;font-weight:500}}
b.hl{{color:var(--accent2)}}
caption{{caption-side:bottom;text-align:left;font-size:11px;color:var(--mut);
line-height:1.6;padding:8px 2px 0}}
code{{font-family:Consolas,monospace;background:#e9eef0;padding:1px 5px;
border-radius:4px;font-size:12px}}
</style></head><body><div class="wrap">

<div class="head">
<p class="org">SJTU-TPMSHX · 换热器快速设计</p>
<h1>10 kW 空冷器 — TPMS 换热芯方案预测报告</h1>
<p class="sub">迎风一边 750 mm 固定(甲方确认)× 流动布置(叉流 / 逆流)× 许用压降 5% / 10% · 生成于 {time.strftime('%Y-%m-%d')}</p>
</div>

<div class="body">
<p class="note risk">历史研究模板：结果表读取既有计算缓存；摘要、精度数字及关键结论沿用 2026-06 文案，不代表当前 TM1 的设计或实验精度验收。缓存的代码、模型及原生状态须另行核对。</p>

<p class="abstract">针对 10 kW 空冷器需求,采用增材制造(3D 打印)<b>TPMS</b>(三周期极小曲面,一种连续曲面多孔结构)
换热芯,将约 0.25 m³/s 热空气冷却至 ≤45 °C,热量由 ≤38 °C 冷却水带走。迎风面一边固定 750 mm、
另一边与深度自由,以体积最小为目标对 Diamond / Gyroid 曲面 × 多种晶胞枚举定尺。
结果:4 套候选(叉流 / 逆流 × 5% / 10% 压降)<b>全部满足</b>换热量与出风温约束,芯体仅
<b>0.49–0.64 L</b>、2.1–2.7 kg。该外形下<b>叉流与逆流性能相近</b>(水侧压降均 &lt;0.3%),逆流略优。
唯一须确认的前提:许用压降取 5–10% 偏高,空气侧需高静压鼓风机。</p>

<div class="stats">
<div class="stat"><div class="v">10 kW</div><div class="l">单台换热量 · 达标</div></div>
<div class="stat"><div class="v">0.49–0.64 L</div><div class="l">换热芯体积</div></div>
<div class="stat"><div class="v">≤45 °C</div><div class="l">出风温 · 全工况满足</div></div>
<div class="stat"><div class="v">叉≈逆</div><div class="l">两布置性能相近</div></div>
</div>

<h2><span class="n">结论</span>评估结论与建议</h2>
<div class="note"><span class="tag">方案可行,结构紧凑。</span>
迎风一边固定 750 mm,4 套候选(叉流 / 逆流 × 压降 5% / 10%)均满足 10 kW 换热量与出风 ≤45 °C 约束,
芯体仅 <b class="hl">0.49–0.64 L、2.1–2.7 kg</b>,均为 Diamond l4/t0.6 构型;外形为扁高薄板(宽 34–48 mm × 高 750 mm × 深 17–19 mm)。</div>
<div class="note"><span class="tag">叉流与逆流性能相近,推荐逆流(略优)。</span>
该外形下水侧压降两者都极低(叉流 0.18–0.27% / 逆流 0.02–0.04%),体积几乎相同;
逆流水阻略低、对数平均温差略大,叉流则进出口集管更易做。<b>代表件:逆流 Diamond l4/t0.6 —
压降≤10% 时 0.49 L / 2.1 kg,≤5% 时 0.64 L / 2.7 kg</b>(叉流近乎等效,可作备选)。</div>
<div class="note flag"><span class="tag">唯一须甲方确认的前提:</span>
许用压降取 5–10% 偏高 —— 空气侧压降达 <b>7–24 kPa</b>,需<b>高静压鼓风机</b>(常规轴流风机不足以克服)。
水侧不构成约束。</div>

<h2><span class="n">①</span>设计任务与工况</h2>
{_spec_block()}
<h3>喂入模型的三个计算工况(含上述推测值)</h3>
<div class="card">
<p>将一股<b>热空气</b>冷却,热量经金属壁传递至<b>冷却水</b>侧带走。三个工况对应甲方草稿给定的
<b>三档空气压力</b>(0.145 / 0.182 / 0.242 MPa),须由<b>同一台</b>换热器同时满足:</p>
<table><thead><tr><th>工况</th><th>空气进→出温 °C</th><th>空气绝压 kPa</th><th>空气流量 kg/s</th>
<th>水进→出温 °C</th><th>水流量 kg/s</th></tr></thead><tbody>{case_rows}</tbody></table>
<p class="legend">注:进风温由「换热量 10 kW + 空气流量 + 出风 45 °C」反算;空气压力为甲方给定加压值(按绝压计);
水温差约 2 K(由 10 kW + 冷却水量反算)。</p>
</div>

<h2><span class="n">②</span>计算方法</h2>
<div class="card">
<p>采用本课题组开发的<b>快速换热设计模型</b>:基于体积平均的局部非平衡(LTNE)多孔介质传热模型,
非逐网格 CFD,单工况秒级求解。对两类 TPMS 曲面(Diamond、Gyroid)× 多种晶胞参数
(晶胞边长 <i>l</i>、壁厚 <i>t</i>)共 40 种构型逐一定尺,在满足<b>换热量与两侧压降约束</b>下取
<b>体积最小</b>方案(增材制造成本与紧凑性导向);空气、水物性按进出口<b>平均温度</b>取值。</p>
<p style="margin:8px 0 0"><b>验证依据:</b>底层换热 / 压降关联式已在上海某 air-water TPMS 换热器
<b>16 组实验工况</b>上标定 —— 换热量 Q 平均误差约 <b>2%</b>;水侧压降存在约 <b>45%</b> 系统偏差
(已知,主因实验件进出口口径与表面粗糙,见⑤注意事项)。本报告所报换热量可信度高,压降为量级估计。</p>
</div>

<h3>流动布置示意(叉流 vs 逆流)</h3>
{FLOW_FIG}

<h2><span class="n">③</span>结果汇总(各方案最小体积件)</h2>
<table><thead><tr><th>流动布置</th><th>压降上限</th><th>推荐构型</th>
<th>宽×高×深 mm</th><th class="num">体积 L</th><th class="num">重量 kg</th>
<th class="num">单股流体换热面积 m²</th>
<th class="num">气侧压降 %</th><th class="num">水侧压降 %</th><th class="num">出风 °C</th></tr></thead>
<tbody>{comp_rows()}</tbody>
<caption>表 1 · 各方案最小体积件(迎风一边 = 750 mm 固定)。灰底行 = 逆流(略优)。「构型」中 <i>l</i> = 晶胞边长 mm、<i>t</i> = 壁厚 mm。
<b>单股流体换热面积</b> = 面积密度 A<sub>0</sub>(Diamond l4/t0.6 ≈ 801 m²/m³)× 芯体体积;两股流体由<b>同一 TPMS 曲面分隔</b>、各接触一侧,故<b>气侧 = 水侧</b>(同一换热面)。
气 / 水侧压降<b>%</b> = 三个工况各自压降占该侧进口绝压之比(斜杠分隔)。宽 / 高 = 迎风面尺寸,深 = 气流穿过芯体的流程长度。
压降均为<b>芯体值</b>(全断面均匀进出假设,不含进出口管道 / 集管损失);
重量 = 固体体积分数 (1−ε)×体积×密度(304 不锈钢,7900 kg/m³,ε = 孔隙率,TPMS 为多孔骨架非实心)。</caption></table>

<h2><span class="n">④</span>关键结论(决策依据)</h2>
<div class="note"><span class="tag">1. 叉流 / 逆流性能相近,水侧均无忧。</span>边 = 750 mm 下水从短边(宽 34–48 mm)横穿、
过流截面大(Lx×750),故<b>两布置水侧压降都极低</b>(叉流 0.18–0.27% / 逆流 0.02–0.04%),体积几乎相同。
逆流水阻更低 + 对数平均温差更大 → <b>略占优,推荐</b>;叉流进出口集管更易做,可作备选。
<i class="mut">(均为<b>芯体值</b>;实物水侧仍须叠加进出口管道 / 集管损失 — 见注意事项)</i></div>
<div class="note"><span class="tag">2. 芯体外形 = 扁高薄板。</span>
边 750 mm 固定 → 宽仅 34–48 mm × 高 750 mm × 深 17–19 mm。
气侧是控制阻力,迎风随压降上限自动定宽;高 750 mm 超单次打印尺寸,须分段拼接。</div>
<div class="note flag"><span class="tag">3. 放宽许用压降可缩小体积,但增大风机能耗。</span>
压降上限 5%→10% 时体积 0.64→0.49 L;但空气侧压降达 <b>7–24 kPa</b>,须配高静压鼓风机。</div>
<div class="note risk"><span class="tag">4. 本结果为预测,非最终设计。</span>
压降为芯体理论值(不含进出口接管损失,实物需另计);进风温与空气压力为反算 / 假设值;
个别方案迎面风速偏低,换热关联式略有外推 — 详见注意事项。</div>

<h2><span class="n">⑤</span>注意事项(Caveats)</h2>
<div class="card"><ul style="margin:0;padding-left:20px">
<li><b>许用压降 5–10% 偏高</b>:空气侧 7–24 kPa 须高静压鼓风机(非常规轴流风机);加压回路下可接受。</li>
<li><b>进出口按「全断面均匀进出」建模</b>:模型令流体在整个迎风面 / 侧面上均匀进出,
未含从管接口经集管分配到全断面的损失。真实水侧由<b>管道接口</b>进出(非 750 mm 宽缝)→ 另有分配 / 集管压降。
<b style="color:#7a1f1f">故芯体水侧压降很小(如逆流 ≤0.04%)≠ 系统水侧压降小</b>:此时真实水阻可能由未建模的集管主导,选型阶段须单独核算。</li>
<li><b>压降均为芯体理论值</b>,约数十 % 不确定度,<b>不含进出口集管 / 风口损失</b>(实物需另计)。</li>
<li><b>换热关联式适用范围</b>:大迎风时迎面风速偏低,部分工况略超关联式标定区间(明细表已标「验证域」);
水侧关联式各拓扑用自身实拟合(Diamond / Gyroid 各自直拟,无借用)。</li>
<li><b>制造</b>:芯体高 750 mm 超单次打印尺寸,须<b>分段拼接</b>;进风温与空气压力须与实物核对。</li>
</ul></div>

<h2><span class="n">⑥</span>配套文件</h2>
<p style="font-size:13.5px">详细数据见 Excel <code>quick_design_aircooler_汇报.xlsx</code>:
「对比总览」+ 叉流 / 逆流 × 5% / 10% 共 4 张枚举明细(各 40 构型 × 含逐工况压降%)。</p>

</div></div></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[html 汇报] {path}")

CASES = build_cases()           # 工况表 (供 html 工况展示; dPlim 在此不重要)

if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "sanity"
    cases = build_cases()
    t0 = time.time()
    if mode == "sanity":
        d = size_fixed_cell(cases, "Diamond", 6.0, 0.4, "cross", prop_model="mean")
        show(d, "square Diamond,6,0.4")
    elif mode == "square":
        results, best = enumerate_select(cases, "cross", n_jobs=-1, prop_model="mean")
        for d in results:
            if d.feasible:
                show(d, f"sq {d.topo},{d.l},{d.t}")
        if best:
            show(best, "BEST-square min-V")
    elif mode == "rect":
        results, best = enumerate_select(cases, "cross", n_jobs=-1,
                                         prop_model="mean", height=H_RECT)
        for d in results:
            if d.feasible:
                show(d, f"rect {d.topo},{d.l},{d.t}", height=H_RECT)
        if best:
            show(best, "BEST-rect min-V", height=H_RECT)
    elif mode in ("report", "rehtml"):
        arr = sys.argv[2] if len(sys.argv) > 2 else "cross"    # cross / counter
        sfx = "" if arr == "cross" else f"_{arr}"
        xlsx_out = XLSX_OUT.replace(".xlsx", f"{sfx}.xlsx")
        html_out = HTML_OUT.replace(".html", f"{sfx}.html")
        cache = CACHE.replace(".pkl", f"{sfx}.pkl")
        import pickle
        if mode == "report":
            runs = []                          # (key, label, results, height)
            for frac, lab in [(0.05, "5%"), (0.10, "10%")]:
                cs = build_cases(dp_frac=frac) # 两侧 dP ≤ frac × 进口绝压
                print(f"[run] {arr} 解读1 一条边750 @气水≤{lab} (rect) ...")
                edge, be = enumerate_select(cs, arr, n_jobs=-1, prop_model="mean",
                                            height=H_RECT)
                runs.append((f"解读1_{lab}", f"解读1 一条边750 · 气水≤{lab}", edge, H_RECT))
                print(f"[run] {arr} 解读2 总面积750 @气水≤{lab} ...")
                area, ba = enumerate_area(cs, AREA2, arr, prop_model="mean")
                runs.append((f"解读2_{lab}", f"解读2 总面积750 · 气水≤{lab}", area, None))
                show(be, f"解读1 @{lab} min-V", height=H_RECT)
                if ba: show(ba, f"解读2 @{lab} min-V")
                else: print(f"[解读2 @{lab}] 无可行")
            with open(cache, "wb") as fh: pickle.dump(runs, fh)
            print(f"[cache] {cache}")
        else:                                  # rehtml: 从缓存重写, 不重算
            with open(cache, "rb") as fh: runs = pickle.load(fh)
        write_xlsx_sweep(xlsx_out, runs)
        write_html_sweep(html_out, runs, AREA2, arr=arr)
    elif mode == "combined":                    # 汇报版: 合并叉流+逆流缓存 → 1 xlsx + 1 html
        import pickle
        with open(CACHE, "rb") as fh: cross = pickle.load(fh)
        with open(CACHE.replace(".pkl", "_counter.pkl"), "rb") as fh: counter = pickle.load(fh)
        # 750 = 单边边长 (甲方确认) → 仅取解读1, 弃解读2(总面积)
        cross = [r for r in cross if "解读1" in r[0]]
        counter = [r for r in counter if "解读1" in r[0]]
        write_combined_xlsx(XLSX_RPT, cross, counter)
        write_combined_html(HTML_RPT, cross, counter, AREA2)
    print(f"\n[elapsed] {time.time()-t0:.1f}s")
