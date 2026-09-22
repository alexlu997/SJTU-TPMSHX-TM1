"""report_template.py — HTML 报告模板（瑞士工程设计语言）+ MathML 公式助手.

现行版式：「瑞士工程」（用户选定 2026-07-15，试衣间
reports/design_specimen.html 方案三）——暖白底、黑标尺线/黑框数字带、
红色单强调、无圆角无投影；标题与正文使用微软雅黑（Segoe UI 回退），
数据 Consolas、公式 Cambria Math。结构与组件类名沿袭首版 thariqs 模板
(thariqs.github.io/html-effectiveness)，报告脚本无需随视觉层改动。
生成自包含离线 HTML 报告时统一 import 本模块，勿在各脚本里复制 CSS。

用法
----
    from sjtu_tpmshx.validation.report_template import (
        BASE_CSS, page, section, mi, mn, mo, mrow, msub, msup, mfrac,
        paren_pow, math_block)

    formula = math_block(
        mi("Nu"), mo("="), mn("0.1610"), mo("·"),
        msup(msub(mi("Re"), mi("b")), mn("0.7264")),
        paren_pow(mfrac(msub(mi("D"), mi("h")), mi("L")), "-0.3808"))
    html = page(title=..., eyebrow=..., h1=..., intro=..., toc=[...],
                body=section("01", "模型与系数", intro_text, inner_html) + ...,
                footer_left=..., footer_right=...)

硬性规则（历史教训，勿回退）
--------------------------
1. **公式一律用 MathML**（<math>，浏览器原生，Chrome/Edge >= 109 / Firefox /
   Safari 均支持）。禁止用 CSS flex 手搓分式 —— 2026-07-15 首版用
   `display:inline-flex` 堆叠分子分母，实测基线下坠、括号不随分式拉伸
   （见当日报告截图）。MathML 的 <mo> 括号自动拉伸、<mfrac> 自动对齐基线。
2. **多字符变量（Re/Pr/Nu）要 mathvariant="italic"** —— MathML 规范里
   多字符 <mi> 默认直立体，单字符默认斜体；本模块 mi() 已统一处理。
3. **matplotlib 图先设 CJK 字体**（font.sans-serif 前置 Microsoft YaHei，
   axes.unicode_minus=False），否则中文变方框、负号缺字形。
4. 表格数字列加 font-variant-numeric: tabular-nums（已在 CSS 里）。
5. 图表数据标记色用 dataviz 已验证调色板（首 4 槽全对安全:
   #2a78d6 / #008300 / #e87ba4 / #eda100），模板色（clay/olive）只作 UI 强调，
   不进数据标记。
6. **质量地板内置于模板，勿在报告脚本里关掉**（frontend-design skill,
   2026-07-15 过审）：:focus-visible 键盘焦点环；prefers-reduced-motion
   下关平滑滚动与过渡；@media print 隐藏筛选/TOC、放开表格高度；
   TOC 滚动定位高亮（page() 自带 IntersectionObserver，无依赖）；
   表格斑马纹 + 行悬停 + 排序方向指示（th 内放 <span class="dir">，
   JS 置 ▲/▼）；筛选空态给指引文案（.empty），不留白屏。
7. **长表（≳1000 行）必须虚拟滚动**——整体 innerHTML 数千行每次排序重解析
   几万个单元格，实测明显卡顿（2026-07-15，7000 行表）。实现采用
   固定行高 + 上下 spacer 行 + 只画视口
   ±缓冲、scroll 用 requestAnimationFrame 节流、首帧后 offsetHeight 校准
   行高；斑马纹改绝对行号 `.zr` 类并在 extra_css 里关掉模板的
   nth-child 版（虚拟滚动下 nth-child 奇偶随滚动跳变）。
8. **每个 <figure> 必须带 <figcaption>**——图号由 CSS 计数器自动生成
   （精修 D），无 figcaption 的图会静默占号导致编号跳跃。
9. **matplotlib 图必须透明底**（2026-07-16 融底优化 A）：rcParams
   `figure.facecolor="none"` + `ax.set_facecolor("none")` +
   `savefig(..., transparent=True)`，legend/标注框底色用 IVORY
   （遮点用，与纸面同色）。模板 figure CSS 已无白底无边框——
   不透明的白底 PNG 会在米色纸面上留一块白斑。
10. **图表内联 SVG**（2026-07-16 优化 A2）：rcParams
    `svg.fonttype="none"`（文字保留真实文本——与页面同字体渲染、
    可选中可检索、体积更小），`savefig(format="svg")` 后去掉 XML 头
    直接内联进 <figure>。**每图 savefig 前必须设唯一
    `svg.hashsalt`**——否则同页多图的 clipPath id 撞车互相裁剪。
    图外包 `<div class="figwrap" role="img" aria-label="…">` 代替 alt。
"""
from __future__ import annotations

# ── design tokens（方案三「瑞士工程」, 用户选定 2026-07-15,
#    试衣间 reports/design_specimen.html; 取代 thariqs ivory 视觉层,
#    组件类名/结构不变。历史: ivory+clay → 字体B → 字体D → 本方案）──
IVORY, PAPER, SLATE, CLAY = "#FBFAF7", "#FFFFFF", "#111111", "#D0342C"
ACCENT = CLAY                       # 语义别名: 瑞士红
OAT, OLIVE = "#E4E1D8", "#788C5D"   # legacy, 勿新增使用
G100, G200, G300, G500, G700 = ("#F1EFE9", "#E4E1D8", "#C9C6BE",
                                "#6E6C66", "#3A3936")
# dataviz validated categorical palette — first 4 slots (all-pairs safe)
VIZ1, VIZ2, VIZ3, VIZ4 = "#2a78d6", "#008300", "#e87ba4", "#eda100"
# 双系列图的首选配对：蓝 + 橙（palette slot 6；用户偏好 2026-07-15，
# 校验器全 PASS：CVD ΔE 24.7 / normal 33.6）。注意橙 (#eb6834) 与
# 黄 (VIZ4 #eda100) 同暖色系，勿在同一图内混用两者。
VIZ_ORANGE = "#eb6834"
PAIR_A, PAIR_B = VIZ1, VIZ_ORANGE
# sCO2 对标图三色（用户指定 2026-07-16, 蓝紫青单色系家族; 取代此前
# Okabe-Ito 方案）: hot 藏青方框 / cold 亮青实心圆 / CFD 浅紫三角+虚线。
# validate_palette.js 记录: 亮青对米色底对比 1.4:1、浅紫 2.06:1（WARN,
# 用户知情选定）—— 形状与线型冗余因此更不可省, 勿单靠颜色编码。
HOT_C, COLD_C, CFD_C = "#1B2248", "#6AE8FF", "#AAAEE6"

# ── 图表格式常量 + 期刊轴样式（2026-07-16 统一所有误差/对比图的单一来源;
#    历史: 各脚本手写样式漂移 —— 标题 10/10.5/11.5、刻度 8.5/9、
#    图例 8/9、parity 半框外向刻度, 混用不齐）─────────────────────────
CHART_TITLE_FS = 10.5    # 面板标题（loc="left"）
CHART_TICK_FS = 9        # 刻度数字
CHART_LABEL_FS = 11      # 轴标签（斜体）
CHART_LEGEND_FS = 8      # 图例
CHART_ANNO_FS = 10.5     # 图内公式/结论标注
# 图内标注统一盒式: 米色底（遮点, 与纸面同色）+ 灰细边
ANNO_BOX = dict(boxstyle="round,pad=0.4", fc=IVORY, ec=G300, lw=0.9)


def style_journal_ax(ax, xlabel="", ylabel="", title=None):
    """期刊风格轴（用户选定 2026-07-15）: 全框黑边 + 内向刻度（含上右）
    + 浅网格 + 左对齐标题。所有报告图表统一调这里，勿在脚本内手写复制品。
    xlabel/ylabel 传空串则不设（多面板共享轴时只标边缘面板）。"""
    ax.set_facecolor("none")
    ax.tick_params(colors=SLATE, labelsize=CHART_TICK_FS, direction="in",
                   top=True, right=True)
    for sp in ax.spines.values():
        sp.set_color(SLATE)
        sp.set_linewidth(1.0)
    ax.grid(True, color=G200, linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=CHART_LABEL_FS, style="italic")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=CHART_LABEL_FS, style="italic")
    if title:
        ax.set_title(title, color=SLATE, fontsize=CHART_TITLE_FS,
                     loc="left", pad=8)

BASE_CSS = """
  :root {
    /* 瑞士工程设计令牌（2026-07-15 方案三; 字体 2026-07-16 改全雅黑）:
       暖白底、黑标尺线、红色单强调, 无圆角、无投影 */
    --ivory:#FBFAF7; --paper:#FFFFFF; --slate:#111111; --clay:#D0342C;
    --g100:#F1EFE9; --g200:#E4E1D8; --g300:#C9C6BE;
    --g500:#6E6C66; --g700:#3A3936;
    /* 字体（2026-07-16 用户裁决: 全面微软雅黑, 替换 Bahnschrift/等线）:
       标题雅黑 700、正文雅黑常规、数据/眉题 Consolas、公式 Cambria Math */
    --head: "Microsoft YaHei", "Segoe UI", sans-serif;
    --serif: var(--head);              /* 兼容别名: 旧组件引用 --serif */
    --body: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    --sans: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    --mono: Consolas, "Cascadia Mono", ui-monospace, monospace;
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body { margin:0; background:var(--ivory); color:var(--slate);
        font-family:var(--body); font-size:16px; line-height:1.6;
        -webkit-font-smoothing:antialiased; }
  /* 阅读宽度（2026-07-16 精修 A）: 散文块统一 42em ≈ 42 中文字/行
     （最佳行长 CJK ~35-45 字; 参照 webtypography.net / USWDS） */
  :root { --measure:42em; }
  .wrap { max-width:1120px; margin:0 auto; padding:0 32px 120px; }
  @media (max-width:640px) { .wrap { padding:0 18px 80px; } }

  :focus-visible { outline:2px solid var(--clay); outline-offset:2px; }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior:auto; }
    *, *::before, *::after { transition:none !important;
                             animation:none !important; }
  }

  header.masthead { padding:56px 0 0; margin-bottom:14px; }
  .eyebrow { font-family:var(--mono); font-size:12px; letter-spacing:.08em;
             color:var(--g500); margin-bottom:16px;
             display:flex; align-items:center; gap:12px; }
  .eyebrow::before { content:""; width:26px; height:2.5px; background:var(--clay); }
  h1 { font-family:var(--head); font-weight:700;
       font-size:clamp(30px,4.4vw,42px); line-height:1.1;
       letter-spacing:-.01em; margin:0 0 18px; max-width:26ch; }
  h1 em { font-style:normal; color:var(--clay); }
  .intro { font-size:15px; color:var(--g700); margin:0 0 24px; max-width:var(--measure); }
  .intro code, .sec-intro code { font-family:var(--mono); font-size:.86em;
       background:var(--g100); padding:1px 5px; }
  /* 中文排版精修（优化 B, 2026-07-16）: 散文块两端对齐 + inter-ideograph
     （CJK 无空格, 靠字间均摊消除右缘参差; Chromium/Edge 支持）;
     标题 balance / 段落 pretty（不支持的浏览器静默降级） */
  .intro, .sec-intro, .speclist .sv, figcaption, .callout, .note, .tile p {
    text-align:justify; text-justify:inter-ideograph; text-wrap:pretty; }
  h1, .sec-head h2 { text-wrap:balance; }
  /* 页头双栏（2026-07-16 精修 E）: 左标题+导语, 右"速览"事实栏, 用满右侧留白 */
  .mast-grid { display:grid; grid-template-columns:minmax(0,1fr) 296px;
               gap:52px; align-items:start; }
  @media (max-width:900px){ .mast-grid { grid-template-columns:1fr; gap:24px;
               align-items:start; } }
  .mast-aside { border-top:2.5px solid var(--slate); padding-top:12px; }
  .mast-aside .at { font-family:var(--mono); font-size:10.5px;
               letter-spacing:.08em; color:var(--g500); margin-bottom:8px; }
  .mast-aside .row { display:flex; justify-content:space-between; gap:16px;
               padding:7px 0; border-bottom:1px solid var(--g200);
               font-size:12.5px; align-items:baseline; }
  .mast-aside .row:last-child { border-bottom:none; }
  .mast-aside .row .k { color:var(--g500); white-space:nowrap; }
  .mast-aside .row .v { color:var(--slate); text-align:right;
               font-variant-numeric:tabular-nums; }
  .mast-aside .row .v b { font-family:var(--head); font-weight:700;
               color:var(--clay); }
  .mast-aside .row code { font-family:var(--mono); font-size:11px;
               color:var(--g700); }
  /* masthead 收尾: 3px 黑标尺线（瑞士签名元素） */
  nav.toc { display:flex; flex-wrap:wrap; gap:2px 6px; padding:10px 0 12px;
            border-top:3px solid var(--slate);
            /* 精修 B (2026-07-16): 吸顶导航 —— 长报告随时可跳转
               2026-07-16 放大: 编号大号红 + 标签雅黑, 强化功能层级 */
            position:sticky; top:0; z-index:20; background:var(--ivory); }
  nav.toc.stuck { border-bottom:1px solid var(--g200);
                  box-shadow:0 4px 12px -8px rgba(0,0,0,.25); }
  nav.toc a { display:inline-flex; align-items:baseline; gap:8px;
              padding:8px 14px; text-decoration:none; color:var(--g700);
              border-bottom:3px solid transparent; }
  nav.toc a .n { font-family:var(--mono); font-size:16px; font-weight:700;
                 color:var(--clay); }
  nav.toc a .txt { font-family:var(--head); font-weight:700; font-size:15px;
                   color:var(--g700); }
  nav.toc a:hover { border-bottom-color:var(--g300); }
  nav.toc a:hover .txt { color:var(--slate); }
  nav.toc a.active { border-bottom-color:var(--clay); }
  nav.toc a.active .txt { color:var(--slate); }
  @media (max-width:640px){ nav.toc a{ padding:6px 10px; }
                            nav.toc a .n{ font-size:14px; }
                            nav.toc a .txt{ font-size:13px; } }

  section { margin-top:64px; scroll-margin-top:64px; }
  .sec-head { display:flex; align-items:baseline; gap:16px;
              border-left:5px solid var(--clay); padding-left:16px;
              margin-bottom:8px; }
  /* 精修 C (2026-07-16): 大号幽灵节码 —— 瑞士签名, 强化翻阅节奏 */
  .sec-head .idx { font-family:var(--head); font-size:56px; font-weight:700;
                   color:var(--g200); line-height:.85; flex-shrink:0;
                   letter-spacing:-.02em; user-select:none; }
  .sec-head h2 { font-family:var(--head); font-weight:700; font-size:22px;
                 margin:0; letter-spacing:0; }
  .sec-head .count { font-family:var(--mono); font-size:11px;
                     color:var(--g500); }
  .sec-intro { font-size:14px; color:var(--g700); max-width:var(--measure);
               margin:0 0 24px 21px; }
  .sec-body { margin-left:21px; }
  @media (max-width:640px) { .sec-intro,.sec-body { margin-left:0; } }

  /* tile: 卡片 → 黑顶线分栏（无底色无圆角） */
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
           gap:0 28px; }
  .tile { border-top:2.5px solid var(--slate); padding:12px 2px 8px; }
  .tile-head { font-family:var(--head); font-weight:700; font-size:17px;
               margin-bottom:8px; display:flex; align-items:center; gap:10px; }
  .count { font-family:var(--mono); font-size:11px; color:var(--g500); }
  .tile p { margin:6px 0; font-size:13.5px; color:var(--g700); }
  .tile .lbl { display:block; font-family:var(--mono); font-size:10.5px;
               letter-spacing:.05em; color:var(--g500); }
  .tile b { color:var(--slate); } .sep { color:var(--g300); }

  /* hero: 黑框数字带（上下 2.5px 黑线, 格间 1px 发丝线, 零间隙） */
  .heroes { display:grid; gap:0; margin-bottom:20px;
            border-top:2.5px solid var(--slate);
            border-bottom:2.5px solid var(--slate);
            grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); }
  .hero { padding:13px 16px 11px; }
  .hero + .hero { border-left:1px solid var(--g300); }
  .hero .lbl { font-family:var(--mono); font-size:10.5px;
               letter-spacing:.05em; color:var(--g500); margin-bottom:3px; }
  .hero .big { font-family:var(--head); font-weight:700; font-size:33px;
               line-height:1.12; color:var(--slate);
               font-variant-numeric:tabular-nums; }
  .hero .big .u { font-size:16px; color:var(--g500); font-weight:400; }
  .hero .sub { font-size:11.5px; color:var(--g500); margin-top:3px;
               white-space:nowrap; }

  /* 公式块: 黑顶线段落, 无卡片 */
  .fcard { border-top:2.5px solid var(--slate); padding:10px 2px 6px;
           margin-bottom:16px; }
  .fcap { font-family:var(--mono); font-size:11px; letter-spacing:.05em;
          color:var(--g500); margin-bottom:6px; }
  .formula { text-align:center; padding:4px 0 10px;
             overflow-x:auto; overflow-y:hidden; }
  .formula math { font-size:21px; }
  .formula .frole { font-family:var(--mono); font-size:11px;
                    color:var(--g500); margin-right:10px; }
  .note { font-size:13px; color:var(--g700); max-width:var(--measure); }
  .note math { font-size:15px; }

  /* 公式对比表: booktabs 式（黑重线 + 灰行线, 无竖线无底色） */
  .cmp-wrap { border-top:2.5px solid var(--slate);
              border-bottom:2.5px solid var(--slate); }
  table.cmp { width:100%; border-collapse:collapse; }
  .cmp th { font-family:var(--mono); font-size:11px; font-weight:400;
            letter-spacing:.05em; color:var(--g700); text-align:left;
            padding:8px 14px; border-bottom:1.5px solid var(--slate); }
  .cmp td { padding:13px 14px; border-top:1px solid var(--g200);
            text-align:left; vertical-align:middle; }
  .cmp tr:first-child + tr td { border-top:none; }
  .cmp td.topo { font-family:var(--head); font-weight:700; font-size:16px;
                 white-space:nowrap; }
  .cmp math { font-size:17px; }
  .statline { font-size:12.5px; color:var(--g700); margin:10px 2px 0; }
  .statline .g { white-space:nowrap; }
  .statline .d { color:var(--g300); margin:0 6px; }

  /* 结论列强化（优化 C）: 表内关键数值列 —— 红·加重·大半号,
     可选 .kbar 迷你条形指示（宽度 ∝ 数值超出基线量, 报告脚本内联给宽） */
  table td.key { font-family:var(--head); font-weight:700; font-size:16px;
                 color:var(--clay); white-space:nowrap;
                 font-variant-numeric:tabular-nums; }
  .kbar { display:inline-block; height:9px; background:var(--clay);
          opacity:.25; margin-left:10px; vertical-align:1px; }
  /* 数字列右对齐工具类（优化 B）: cmp/spec 默认左对齐,
     纯数值列在报告脚本里标 class="n" */
  .cmp td.n, .cmp th.n, .spec td.n, .spec th.n { text-align:right; }

  /* 图表交互层（优化 D, 2026-07-16）: 点击放大（原生 dialog, 无依赖,
     page() 自动注入 JS）+ 每图可折叠数据表（dataviz 规范的 table view） */
  dialog.lightbox { width:min(96vw,1680px); max-width:none; padding:12px;
                    border:2.5px solid var(--slate); background:var(--ivory); }
  dialog.lightbox::backdrop { background:rgba(17,17,17,.55); }
  dialog.lightbox svg, dialog.lightbox img { width:100%; height:auto;
                    display:block; cursor:zoom-out; }
  details.dtable { margin-top:10px; }
  .dtable summary { font-family:var(--mono); font-size:11px;
                    color:var(--g500); cursor:pointer; user-select:none;
                    padding:2px 0; }
  .dtable summary:hover { color:var(--clay); }
  .dtable .dwrap { max-height:340px; overflow:auto; margin-top:6px;
                   border-top:1.5px solid var(--slate);
                   border-bottom:1.5px solid var(--slate);
                   background:var(--paper); }

  /* 图自动编号（CSS 计数器; figure 必须带 figcaption 否则静默跳号）。
     2026-07-16 撤销边注栏: 宽幅双栏图满宽显示更清晰。
     2026-07-16 融底（优化 A）: 图 PNG 透明底直接坐在米色纸面上
     （报告脚本须 savefig(transparent=True), 见硬性规则 9）——
     去白箱去边框; 图版以黑顶线开版, 图注收灰、不再另加重线。 */
  body { counter-reset: fig; }
  figure { margin:6px 0 34px; counter-increment: fig;
           border-top:2.5px solid var(--slate); padding-top:14px; }
  figure img, figure svg { width:100%; height:auto; display:block;
                           cursor:zoom-in; }
  figcaption { font-size:12.5px; color:var(--g500); margin-top:4px;
               max-width:var(--measure); }
  figcaption::before { content:"图 " counter(fig) " · ";
               font-family:var(--mono); font-weight:600; color:var(--slate); }

  /* 规格定义列表（分类块: 左 mono 标签 + 右内容; 黑顶线, 无卡片） */
  .speclist { border-top:2.5px solid var(--slate); margin-bottom:16px; }
  .speclist .srow { display:grid; grid-template-columns:104px 1fr; gap:22px;
                    padding:12px 0; border-bottom:1px solid var(--g200); }
  .speclist .srow:last-child { border-bottom:none; }
  .speclist .sk { font-family:var(--mono); font-size:11.5px; color:var(--clay);
                  letter-spacing:.04em; padding-top:2px; }
  .speclist .sv { font-size:14px; color:var(--g700); max-width:var(--measure); }
  @media (max-width:560px){ .speclist .srow{ grid-template-columns:1fr; gap:4px; } }

  /* 过滤规则表（booktabs 小表） */
  table.spec { width:100%; border-collapse:collapse; font-size:13.5px;
               margin:4px 0 16px; }
  .spec th { text-align:left; font-family:var(--mono); font-size:11px;
             color:var(--g500); font-weight:400; padding:7px 14px 7px 0;
             border-bottom:1.5px solid var(--slate); }
  .spec td { padding:10px 14px 10px 0; border-bottom:1px solid var(--g200);
             vertical-align:top; }
  .spec td:first-child { font-family:var(--head); font-weight:700;
             white-space:nowrap; }
  .spec td code { font-family:var(--mono); font-size:12px; color:var(--g700); }

  /* 提醒块（左红竖线 + 浅底） */
  .callout { border-left:4px solid var(--clay); background:var(--g100);
             padding:12px 16px; margin-top:8px; font-size:13.5px;
             color:var(--g700); max-width:var(--measure); }
  .callout b { color:var(--slate); }

  /* 工程取用卡（优化 2026-07-16）: 报告核心交付物 —— 红框强调,
     公式可直接抄进求解器; 内嵌 .cmp 表不再套 .cmp-wrap 重线 */
  .usecard { border:2.5px solid var(--clay); background:var(--paper);
             padding:16px 20px 12px; margin:4px 0 8px; }
  .usecard .uc-h { font-family:var(--mono); font-size:11px;
             letter-spacing:.06em; color:var(--clay); margin-bottom:8px; }
  .usecard .uc-h math { font-size:14px; }
  .usecard .uc-note { font-size:12.5px; color:var(--g700); margin-top:10px;
             border-top:1px solid var(--g200); padding-top:8px;
             text-align:justify; text-justify:inter-ideograph; }
  .usecard .uc-note b { color:var(--clay); }

  .filters { display:flex; gap:8px; flex-wrap:wrap; margin:0 0 12px;
             align-items:center; }
  select,input { padding:5px 10px; border:1.5px solid var(--g300);
                border-radius:0; background:var(--paper); font-size:12.5px;
                color:var(--g700); font-family:var(--sans); }
  select:hover,input:hover { border-color:var(--slate); }
  #cnt { font-family:var(--mono); font-size:11.5px; color:var(--g500); }
  #wrap { max-height:600px; overflow:auto;
          border-top:2.5px solid var(--slate);
          border-bottom:2.5px solid var(--slate); background:var(--paper); }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th,td { padding:4px 10px; border-bottom:1px solid var(--g200);
          text-align:right; white-space:nowrap; }
  th { position:sticky; top:0; background:var(--paper); cursor:pointer;
       font-family:var(--mono); font-size:10.5px; letter-spacing:.04em;
       color:var(--g700); z-index:1; user-select:none;
       border-bottom:1.5px solid var(--slate); }
  th:hover { color:var(--clay); }
  th .dir { color:var(--clay); font-size:9px; margin-left:3px; }
  td { font-variant-numeric:tabular-nums; }
  tbody tr:nth-child(even) td { background:#F6F4EE; }
  tbody tr:hover td { background:var(--g100); }
  td:nth-child(-n+3), th:nth-child(-n+3) { text-align:left; }
  td:first-child { font-family:var(--mono); font-size:11.5px; }
  .bad { color:var(--clay); font-weight:600; }
  .empty { padding:32px; text-align:center; color:var(--g500);
           font-size:13px; }

  footer { margin-top:90px; border-top:3px solid var(--slate);
           padding-top:22px; display:flex; justify-content:space-between;
           gap:20px; flex-wrap:wrap; font-size:13px; color:var(--g500); }
  footer .k { font-family:var(--head); font-weight:700; color:var(--g700); }

  /* 打印 / PDF 精装（优化 C, 2026-07-16）: A4 + 页码（Chrome 131+ / Edge
     同内核, 原生 @page 页边距盒; 页眉报告题由 page() 按标题注入）。
     章节整页起（masthead 独占首页成封面）, 关键块不跨页断开。 */
  @page {
    size:A4; margin:16mm 14mm 18mm;
    @bottom-center { content:"第 " counter(page) " 页 · 共 "
                             counter(pages) " 页";
                     font-family:Consolas, monospace; font-size:8.5pt;
                     color:#6E6C66; }
  }
  @media print {
    :root { print-color-adjust:exact; -webkit-print-color-adjust:exact; }
    body { background:#fff; }
    nav.toc, .filters, details.dtable, dialog { display:none; }
    header.masthead { padding:16px 0 0; }
    section { margin-top:28px; break-before:page; }
    #wrap { max-height:none; overflow:visible; border:none; }
    th { position:static; }
    figure, .cmp-wrap, .speclist, table.spec, .heroes, .callout {
      break-inside:avoid; }
    figure img, figure svg { cursor:auto; }
  }
"""

# 图表点击放大灯箱（page() 自动注入; 原生 <dialog>, 无依赖）——
# 点图开灯箱看细节, 点任意处 / Esc 关闭; 克隆节点, 不动原图。
_LIGHTBOX_JS = """<script>
(() => {
  const dlg = document.createElement('dialog');
  dlg.className = 'lightbox';
  dlg.addEventListener('click', () => dlg.close());
  document.body.appendChild(dlg);
  document.querySelectorAll('figure svg, figure img').forEach(el => {
    el.addEventListener('click', () => {
      dlg.innerHTML = '';
      dlg.appendChild(el.cloneNode(true));
      dlg.showModal();
    });
  });
})();
</script>"""

# TOC 滚动定位高亮（page() 自动注入；IntersectionObserver, 无依赖、无动效）
_SCROLLSPY_JS = """<script>
(() => {
  const spy = new IntersectionObserver(es => es.forEach(e => {
    const a = document.querySelector(`nav.toc a[href="#${e.target.id}"]`);
    if (a) a.classList.toggle('active', e.isIntersecting);
  }), {rootMargin: '-35% 0px -55% 0px'});
  document.querySelectorAll('section[id]').forEach(s => spy.observe(s));
  const toc = document.querySelector('nav.toc');
  if (toc)
    addEventListener('scroll', () => {
      toc.classList.toggle('stuck', toc.getBoundingClientRect().top <= 0);
    }, {passive: true});
})();
</script>"""


# ── MathML helpers ────────────────────────────────────────────────────────
# 规则 2：多字符标识符默认直立体，故 mi() 对多字符统一加 mathvariant="italic"
# （Re/Pr/Nu 等无量纲数按本项目惯例排斜体）。传 italic=False 得直立体。

def mi(x: str, italic: bool | None = None) -> str:
    """Identifier. italic=None -> 自动（单字符交给浏览器默认=斜体,
    多字符补 mathvariant="italic"）。"""
    if italic is None:
        italic = len(x) > 1
        if not italic:
            return f"<mi>{x}</mi>"
    attr = ' mathvariant="italic"' if italic else ' mathvariant="normal"'
    return f"<mi{attr}>{x}</mi>"


def mn(x) -> str:
    return f"<mn>{x}</mn>"


def mo(x: str) -> str:
    return f"<mo>{x}</mo>"


def mrow(*items: str) -> str:
    return f"<mrow>{''.join(items)}</mrow>"


def msub(base: str, sub: str) -> str:
    return f"<msub>{base}{sub}</msub>"


def msup(base: str, sup: str) -> str:
    return f"<msup>{base}{sup}</msup>"


def mfrac(num: str, den: str) -> str:
    return f"<mfrac>{num}{den}</mfrac>"


def paren(inner: str) -> str:
    """Stretchy parentheses (native <mo> fences stretch to content)."""
    return mrow(mo("("), inner, mo(")"))


def paren_pow(inner: str, exponent) -> str:
    """( inner ) ^ exponent — 分式加括号带指数的标准写法."""
    return msup(paren(inner), mn(exponent))


def math_block(*items: str) -> str:
    return f'<math display="block">{mrow(*items)}</math>'


def math_inline(*items: str) -> str:
    return f"<math>{mrow(*items)}</math>"


# ── page assembly ─────────────────────────────────────────────────────────

def section(idx: str, title: str, intro: str = "", body: str = "",
            sec_id: str | None = None, count: str = "") -> str:
    sid = sec_id or f"s{idx.lstrip('0') or '0'}"
    cnt = f'<span class="count">{count}</span>' if count else ""
    intro_html = f'<p class="sec-intro">{intro}</p>' if intro else ""
    return f"""
<section id="{sid}">
  <div class="sec-head"><span class="idx">{idx}</span><h2>{title}</h2>{cnt}</div>
  {intro_html}
  <div class="sec-body">{body}</div>
</section>"""


def page(title: str, eyebrow: str, h1: str, intro: str,
         toc: list[tuple[str, str, str]], body: str,
         footer_left: str, footer_right: str,
         extra_css: str = "", scripts: str = "", aside: str = "") -> str:
    """toc: [(编号, 文本, 锚点 id), ...]；aside: 页头右栏"速览"HTML（可空）。"""
    toc_html = "".join(
        f'<a href="#{sid}"><span class="n">{n}</span>'
        f'<span class="txt">{txt}</span></a>'
        for n, txt, sid in toc)
    if aside:
        _mast_lead = (f'<div class="mast-grid"><div class="mast-lead">'
                      f'<h1>{h1}</h1><p class="intro">{intro}</p></div>'
                      f'<aside class="mast-aside">{aside}</aside></div>')
    else:
        _mast_lead = f'<h1>{h1}</h1>\n  <p class="intro">{intro}</p>'
    # 打印页眉 = 报告题（@page 盒 content 无法引用 DOM, 构建时注入）
    _t = title.replace('"', "'")
    extra_css = (f'@page {{ @top-right {{ content:"{_t}"; '
                 f'font-family:Consolas, monospace; font-size:8pt; '
                 f'color:#6E6C66; }} }}\n' + extra_css)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{BASE_CSS}{extra_css}</style></head><body><div class="wrap">

<header class="masthead">
  <div class="eyebrow">{eyebrow}</div>
  {_mast_lead}
  <nav class="toc">{toc_html}</nav>
</header>
{body}
<footer>
  <div class="k">{footer_left}</div>
  <div>{footer_right}</div>
</footer>

</div>
{scripts}{_SCROLLSPY_JS}{_LIGHTBOX_JS}</body></html>"""
