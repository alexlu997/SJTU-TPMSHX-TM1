"""asym_ntop_expressions_html.py — nTop Evaluate-Expression sheet → offline HTML.

Matches the WORKING convention from 组会20260615.pptx (slide 3): nTop's
Evaluate Expression uses the reserved spatial coordinates X, Y, Z (uppercase)
and built-in Pi; the field is 2*Pi*X/L (NOT k*x with a custom k — that leaves
x,y,z "unused"). The unit-cell variable is L.

φ (Gyroid/Diamond) is identical in amplitude to our solver's convention
(range ±1.5), so all δ/C/φ_lo/φ_hi values transfer directly (no rescale).

Three ready-to-paste expressions per topology (δ, C, L as nTop variables):
  solid  = ((φ) − delta)^2 − C^2        # |φ−δ|<C → <0 (the wall; meeting form)
  void_A = ((φ) − delta) + C            # φ < δ−C → <0 (gas, large channel)
  void_B = delta + C − (φ)              # φ > δ+C → <0 (liquid, small channel)
nTop "inside = field < 0". Workflow (slide 3): Evaluate Expression → Multiply
(give the field length) → Box → Boolean Intersect. Per case: just change δ (C
fixed per topology).

Reads geom_cases from sjtu_tpmshx/runs/_out/asym_cfd/asym_cfd_worklist.xlsx.
Output: asym-ntop-expressions.html in the same directory.
TPMSHX_TOOL_OUT_DIR overrides the producer/consumer directory.
Usage: python -m sjtu_tpmshx.runs.cfd_asym.asym_ntop_expressions_html
"""
import html as _html
import os
from pathlib import Path

import pandas as pd

_OUT_DIR = Path(os.environ.get('TPMSHX_TOOL_OUT_DIR',
                               Path(__file__).resolve().parents[1] / "_out" / "asym_cfd"))
XLSX = _OUT_DIR / "asym_cfd_worklist.xlsx"
OUT = _OUT_DIR / "asym-ntop-expressions.html"

# φ in nTop convention (X,Y,Z uppercase spatial coords, Pi built-in, L = cell size)
PHI = {
    "Gyroid": ("sin(2*Pi*X/L)*cos(2*Pi*Y/L) + sin(2*Pi*Y/L)*cos(2*Pi*Z/L) "
               "+ sin(2*Pi*Z/L)*cos(2*Pi*X/L)"),
    "Diamond": ("sin(2*Pi*X/L)*sin(2*Pi*Y/L)*sin(2*Pi*Z/L) "
                "+ sin(2*Pi*X/L)*cos(2*Pi*Y/L)*cos(2*Pi*Z/L) "
                "+ cos(2*Pi*X/L)*sin(2*Pi*Y/L)*cos(2*Pi*Z/L) "
                "+ cos(2*Pi*X/L)*cos(2*Pi*Y/L)*sin(2*Pi*Z/L)"),
}


def _exprs(phi):
    return {
        "solid (壁，组会式)": f"(({phi}) - delta)^2 - C^2",
        "void_A (大/气)": f"(({phi}) - delta) + C",
        "void_B (小/液)": f"C - (({phi}) - delta)",
    }


def _box(label, expr):
    esc = _html.escape(expr)
    return (f'<div class="row"><span class="lab">{label}</span>'
            f'<code class="ex">{esc}</code>'
            f'<button class="cp" onclick="cp(this)" data-x="{esc}">复制</button></div>')


def main():
    g = pd.read_excel(XLSX, sheet_name="geom_cases", engine="openpyxl")
    sections = []
    for tpms in ["Diamond", "Gyroid"]:
        sub = g[g["lattice"] == tpms].sort_values("split_r")
        C = float(sub["C"].iloc[0])
        ex = "".join(_box(k, v) for k, v in _exprs(PHI[tpms]).items())
        rows = []
        for _, r in sub.iterrows():
            a = ' class="anchor"' if r["split_r"] == 1.0 else ""
            rows.append(
                f"<tr{a}><td>{r['split_r']:g}</td><td><b>{r['delta']:.4f}</b></td>"
                f"<td>{C:.4f}</td><td>{r['phi_lo']:.4f}</td><td>{r['phi_hi']:.4f}</td>"
                f"<td class='eps'>{r['eps_A']:.3f}</td><td class='eps'>{r['eps_B']:.3f}</td></tr>")
        sections.append(f"""
  <h2 id="{tpms}">{tpms} <span class="cc">C = {C:g}（族内不变，每 case 只改 delta）</span></h2>
  <div class="exprs">{ex}</div>
  <table>
    <thead><tr><th>r</th><th>delta (改这个)</th><th>C</th><th>φ_lo=δ−C</th>
      <th>φ_hi=δ+C</th><th>ε_A 靶</th><th>ε_B 靶</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>""")

    page = _PAGE.replace("{{BODY}}", "".join(sections))
    OUT.write_text(page, encoding="utf-8")
    print(f"[html] {OUT}  (X,Y,Z conv · 3 exprs/topo · 12-case delta, self-contained)")


_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>nTop 表达式 — 非对称孔隙率 (X,Y,Z 约定)</title>
<style>
:root{--ink:#11151c;--mut:#5b6470;--acc:#014198;--soft:#f3f6fb;--line:#d7dee8;--ok:#0a7d3c;--warn:#b5532a;}
*{box-sizing:border-box}
body{font-family:"Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);
     max-width:1040px;margin:0 auto;padding:26px 30px 70px;line-height:1.6;background:#fff}
h1{font-size:1.46rem;border-bottom:3px solid var(--acc);padding-bottom:12px;margin:0 0 6px}
.sub{color:var(--mut);font-size:.86rem;margin:0 0 20px}
h2{font-size:1.18rem;color:var(--acc);margin:34px 0 10px;border-left:5px solid var(--acc);padding-left:12px}
h2 .cc{color:var(--mut);font-weight:400;font-size:.78rem}
code,.ex{font-family:"Cascadia Code",Consolas,monospace;font-size:.8rem}
.common{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:0 0 8px}
.common b{color:var(--acc)} .common code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:2px 7px}
.fix{background:#fff7ef;border:1px solid #f0d9c4;border-radius:10px;padding:11px 18px;margin:10px 0;font-size:.84rem}
.fix b{color:var(--warn)}
.exprs{margin:8px 0 4px}
.row{display:flex;gap:10px;align-items:flex-start;margin:7px 0}
.lab{flex:0 0 150px;font-size:.78rem;color:var(--mut);padding-top:7px}
.ex{flex:1;background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:8px 11px;
     white-space:pre-wrap;word-break:break-word;color:#16202b}
.cp{flex:0 0 auto;border:1px solid var(--acc);background:#fff;color:var(--acc);border-radius:6px;
     padding:7px 12px;font-size:.76rem;cursor:pointer;transition:all .12s}
.cp:hover{background:var(--acc);color:#fff} .cp.done{background:var(--ok);border-color:var(--ok);color:#fff}
table{border-collapse:collapse;width:100%;margin:12px 0 4px;font-size:.84rem;
     font-variant-numeric:tabular-nums;font-family:"Cascadia Code",Consolas,monospace}
th,td{border-bottom:1px solid var(--line);padding:7px 12px;text-align:center}
thead th{border-top:2px solid var(--acc);border-bottom:1.5px solid var(--acc);font-weight:600;
     font-family:"Source Han Sans SC","Microsoft YaHei",sans-serif}
tbody tr:last-child td{border-bottom:2px solid var(--acc)} tbody tr.anchor{background:#eef6ee}
td.eps{color:var(--ok)}
.note{font-size:.8rem;color:var(--mut);border-left:3px solid var(--acc);background:#fbfcfd;
     padding:9px 16px;border-radius:0 6px 6px 0;margin:14px 0}
</style></head><body>
<h1>nTop 表达式 — 非对称孔隙率（X,Y,Z 约定 · 对齐组会成功法）</h1>
<p class="sub">源自 组会20260615.pptx slide 3 · φ 同振幅 → δ/C 值直接有效 · 离线自包含</p>

<div class="fix">
<b>修正</b>：nTop 用 <b>大写 X,Y,Z</b>（保留空间坐标）+ <b>Pi</b>（内置）+ <b>2*Pi*X/L</b>。
之前 <code>k*x</code>（小写 + 自定义 k）→ x,y,z「unused」。
</div>

<div class="common">
<b>先定变量</b>：<code>L = 5</code>（mm）、<code>delta</code>、<code>C</code>（X,Y,Z,Pi 是 nTop 内置，勿定义）。<br>
<b>nTop 约定</b>：implicit body「inside = 场值 &lt; 0」。<br>
<b>组会工作流</b>（slide 3）：Evaluate Expression → <b>Multiply</b>（给场长度量纲）→ <b>Box</b> → <b>Boolean Intersect</b>。<br>
<b>三个表达式</b>：<code>solid</code> = 组会的固体壁；CFD 要流体 → 用 <code>void_A</code>、<code>void_B</code>（互补半空间，各导一套）。
</div>

<p class="note">每 case 只改 <b>delta</b>（C 族内不变）。建好<b>验体积分数 = ε 靶（绿列）</b>再 mesh。先建 Diamond r1（delta=0）验：void_A 体积分数应 = 0.348。</p>

{{BODY}}

<script>
function cp(b){var t=b.getAttribute('data-x');
  (navigator.clipboard&&navigator.clipboard.writeText(t)||Promise.reject()).then(
    function(){done(b)},
    function(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);
      ta.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(ta);done(b)});}
function done(b){var o=b.textContent;b.textContent='已复制';b.classList.add('done');
  setTimeout(function(){b.textContent=o;b.classList.remove('done')},1100);}
</script>
</body></html>"""


if __name__ == "__main__":
    main()
