"""
生成「不同 δ 孔隙率分配」预览图，base64 嵌入桌面 Phase 1 HTML 占位符。

每 TPMS (Diamond/Gyroid) 一行 4 panel: δ = 0 → 连通极限。
z 中切片着色: A(phi<δ−C) 蓝 / 固体(|带|) 灰 / B(phi>δ+C) 橙。
标注实测 ε_A:ε_B (eps_sides)。图内只用 ASCII+希腊字母 (DejaVu Sans 支持),
中文说明放 HTML caption (避免 matplotlib CJK 缺字)。

用法: python -u runs/asym_porosity_preview.py
"""
import sys
import io
import base64
import os
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _find_C_for_eps
from sjtu_tpmshx.models.asym_geometry import eps_sides, find_delta_max

# P1.7: was a dead C:\Users\ALEX\Desktop path. Default to gitignored
# runs/_out; TPMSHX_TOOL_OUT_DIR overrides.
_OUT_DIR = Path(os.environ.get('TPMSHX_TOOL_OUT_DIR',
                               str(Path(__file__).resolve().parents[1] / "_out")))
_OUT_DIR.mkdir(parents=True, exist_ok=True)
HTML = _OUT_DIR / "TPMS-非对称孔隙率-Phase1-CFD计划.html"
PLACEHOLDER = "<!--TPMS-PREVIEW-->"
N = 200
TARGET_POROSITY = 0.85          # solid ~15%, 通道清晰
CMAP = ListedColormap(["#2563eb", "#334155", "#f59e0b"])  # A / solid / B


def _render(tpms: str) -> str:
    phi = _phi_grid(tpms, N)
    C = _find_C_for_eps(phi, TARGET_POROSITY)
    dmax = find_delta_max(phi, C)
    deltas = [0.0, 0.4 * dmax, 0.7 * dmax, dmax]
    sl0 = phi[:, :, N // 2]

    fig, axes = plt.subplots(1, 4, figsize=(11, 3.0))
    for ax, d in zip(axes, deltas):
        eA, eB, _ = eps_sides(phi, C, d)
        cat = np.ones_like(sl0, dtype=int)      # 1 = solid
        cat[sl0 < d - C] = 0                      # A
        cat[sl0 > d + C] = 2                      # B
        ax.imshow(cat.T, origin="lower", cmap=CMAP, vmin=0, vmax=2,
                  interpolation="nearest")
        ax.set_xticks([]); ax.set_yticks([])
        r = eA / eB if eB > 1e-6 else float("inf")
        ax.set_title(f"δ={d:.2f}   ε_A:ε_B = {r:.1f}:1\n"
                     f"ε_A={eA:.2f}  ε_B={eB:.2f}", fontsize=8.5)
    fig.suptitle(f"{tpms}  —  offset δ: 0 (symmetric) → connectivity limit "
                 f"(A=blue grows, B=orange shrinks, solid=grey)", fontsize=10, y=1.04)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    d_b64 = _render("Diamond")
    g_b64 = _render("Gyroid")

    img = ('display:block;width:100%;border-radius:10px;'
           'border:1px solid #e6ebf2;margin:0')
    section = f'''<div style="margin:16px 0 0">
  <figure style="margin:0 0 14px">
    <img src="data:image/png;base64,{d_b64}" alt="Diamond different-porosity preview" style="{img}">
    <figcaption style="font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:#94a3b8;margin-top:5px">Diamond — δ=0 对称 50/50 → 连通极限 ≈ 2.9:1（z 中切片，实测 ε 标注）</figcaption>
  </figure>
  <figure style="margin:0">
    <img src="data:image/png;base64,{g_b64}" alt="Gyroid different-porosity preview" style="{img}">
    <figcaption style="font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:#94a3b8;margin-top:5px">Gyroid — δ=0 对称 50/50 → 连通极限 ≈ 2.9:1</figcaption>
  </figure>
  <div style="display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:12px;font-size:13px;color:#475569">
    <span><span style="display:inline-block;width:13px;height:13px;background:#2563eb;border-radius:3px;vertical-align:-2px;margin-right:5px"></span>流体 A（得益 · 大通道 · 气侧）</span>
    <span><span style="display:inline-block;width:13px;height:13px;background:#334155;border-radius:3px;vertical-align:-2px;margin-right:5px"></span>固体壁（带宽 2C 不变）</span>
    <span><span style="display:inline-block;width:13px;height:13px;background:#f59e0b;border-radius:3px;vertical-align:-2px;margin-right:5px"></span>流体 B（挤压 · 小通道 · 液侧）</span>
  </div>
</div>'''

    html = HTML.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        print(f"FAIL: placeholder {PLACEHOLDER} not found in {HTML.name}")
        return
    html = html.replace(PLACEHOLDER, section)
    HTML.write_text(html, encoding="utf-8")
    print(f"OK: injected 2 preview figures (Diamond+Gyroid) into {HTML.name}")
    print(f"  base64 sizes: Diamond {len(d_b64)//1024}KB  Gyroid {len(g_b64)//1024}KB")


if __name__ == "__main__":
    main()
