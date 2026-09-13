"""asym_plan_to_html.py — render the asym-porosity Phase 1 plan (md) → offline HTML.

Wraps the vault markdown in the SJTU academic template
(`vault/templates/academic-report-template-CN.html`): base64-inlines the header
+ gate-watermark PNGs (self-contained, file:// safe), builds the sidebar TOC from
the h2 sections, maps fenced code → `.eq` blocks and blockquotes → `.callout`.
Unicode formulas (φ/δ/ε/≤/×) render as plain text — no MathJax, fully offline.

Inputs: external research vault, selected by TPMSHX_VAULT_DIR.
Output: sjtu_tpmshx/runs/_out/asym-porosity-phase1-CFD-plan-CN.html
        (TPMSHX_TOOL_OUT_DIR overrides the directory).
Usage from repository root: python -m sjtu_tpmshx.runs.tools.asym_plan_to_html
"""
import base64
import os
import re
from pathlib import Path

import markdown

# P1.7: inputs live in the research vault (a plain-file tree OUTSIDE this
# repo). The old defaults pointed at the dead D:\Postgraduate layout; the
# vault now sits at E:\LWH\vault on this box — TPMSHX_VAULT_DIR overrides.
_VAULT = Path(os.environ.get('TPMSHX_VAULT_DIR', r"E:\LWH\vault"))
MD = _VAULT / "reports" / "engineering" / "asym-porosity-phase1" / "2026-06-05-asym-porosity-phase1-CFD-plan-CN.md"
TPL = _VAULT / "templates" / "academic-report-template-CN.html"
ASSETS = TPL.parent / "assets"
# Output: was a dead C:\Users\ALEX\Desktop path. Default to gitignored
# runs/_out; TPMSHX_TOOL_OUT_DIR overrides.
_OUT_DIR = Path(os.environ.get('TPMSHX_TOOL_OUT_DIR',
                               str(Path(__file__).resolve().parents[1] / "_out")))
_OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = _OUT_DIR / "asym-porosity-phase1-CFD-plan-CN.html"


def _b64(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def main():
    md_text = MD.read_text(encoding="utf-8")

    # title = first '# ...' line; strip it from the body (own <h1> below)
    m = re.search(r"^# (.+)$", md_text, flags=re.M)
    title = m.group(1).strip() if m else "非对称孔隙率 Phase 1 计划"
    body_md = re.sub(r"^# .+\n", "", md_text, count=1)

    # [[wikilink|alias]] / [[a/b/name]] → plain leaf name (no dead links in HTML)
    body_md = re.sub(r"\[\[([^\]]+)\]\]",
                     lambda mm: mm.group(1).split("|")[0].split("/")[-1], body_md)

    # the **Label**: metadata lines before the first '---' are consecutive →
    # markdown would collapse them into ONE run-on paragraph. Hard-break each
    # (two trailing spaces) so they render as separate lines.
    head, sep, tail = body_md.partition("\n---")
    head = head.replace("\n**", "  \n**")
    body_md = head + sep + tail

    # a list directly after a text line (no blank line between) won't be
    # recognized by sane_lists → bullets render inline as run-on " - " text.
    # Insert the missing blank line before each list-start (fence-guarded so
    # formula/code blocks are untouched).
    _item = re.compile(r"^\s*([-*+]|\d+\.)\s")
    out, in_fence = [], False
    for ln in body_md.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(ln)
            continue
        if not in_fence and _item.match(ln):
            prev = out[-1] if out else ""
            if prev.strip() and not _item.match(prev):
                out.append("")
        out.append(ln)
    body_md = "\n".join(out)

    html_body = markdown.markdown(
        body_md, extensions=["tables", "fenced_code", "sane_lists"])

    # fenced code → .eq formula block (monospace, blue left rule, pre-wrap)
    html_body = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>",
                       lambda mm: '<div class="eq">' + mm.group(1) + "</div>",
                       html_body, flags=re.S)
    # blockquote → .callout highlight
    html_body = re.sub(r"<blockquote>\s*(.*?)\s*</blockquote>",
                       lambda mm: '<div class="callout">' + mm.group(1) + "</div>",
                       html_body, flags=re.S)
    # first paragraph = the metadata head → template .meta block
    html_body = html_body.replace("<p>", '<p class="meta">', 1)

    # assign ids to h2 + collect sidebar TOC
    toc = []
    n = [0]

    def _h2(mm):
        inner = mm.group(1)
        plain = re.sub(r"<[^>]+>", "", inner)
        sid = "s%d" % n[0]
        n[0] += 1
        toc.append((sid, plain))
        return '<h2 id="%s">%s</h2>' % (sid, inner)

    html_body = re.sub(r"<h2>(.*?)</h2>", _h2, html_body, flags=re.S)
    nav = "\n".join('  <a href="#%s">%s</a>' % (sid, plain) for sid, plain in toc)

    # reuse template <style>…</head> head + the sidebar-nav <script>
    tpl = TPL.read_text(encoding="utf-8")
    style = tpl[tpl.index("<style>"):tpl.index("</head>")]
    script = tpl[tpl.index("<script>"):tpl.index("</script>") + len("</script>")]

    header_b64 = _b64(ASSETS / "sjtu_header.png")
    gate_b64 = _b64(ASSETS / "sjtu_gate.png")

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{title}</title>
{style}
</head><body>

<div class="layout">
<nav class="sidebar">
  <div class="navtitle">目录</div>
{nav}
</nav>

<main class="content">
  <div class="letterhead"><img src="{header_b64}" alt="上海交通大学"></div>
  <h1>{title}</h1>
{html_body}
  <div class="footer-rule">上海交通大学　Shanghai Jiao Tong University · 非对称孔隙率 Phase 1</div>
</main>
</div>

<div class="watermark"><img src="{gate_b64}" alt=""></div>
{script}
</body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"[html] {OUT}")
    print(f"  {len(html):,} chars · {len(toc)} h2 sections · self-contained (base64 imgs, no CDN)")


if __name__ == "__main__":
    main()
