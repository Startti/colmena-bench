#!/usr/bin/env python3
"""Render the Colmena whitepaper Markdown to a styled, print-ready HTML.

Markdown -> HTML here; HTML -> PDF is done with headless Chrome (see the
companion shell step). Images are kept as relative `assets/...` paths so they
resolve when the HTML is rendered from docs/articles/.
"""
import pathlib
import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "articles" / "colmena-whitepaper.md"
OUT = ROOT / "docs" / "articles" / "colmena-whitepaper.html"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
:root{ --ink:#1f2421; --muted:#5f5e5a; --line:#d9d6cd; --green:#0f6e56; --surf:#f7f6f2; }
*{ box-sizing:border-box; }
body{ font-family: Georgia, "Times New Roman", serif; color:var(--ink);
  line-height:1.5; font-size:10.5pt; margin:0; }
.wrap{ max-width: 820px; margin:0 auto; }
h1,h2,h3,h4{ font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  line-height:1.2; color:#16201b; }
h1{ font-size:23pt; margin:0 0 4pt; letter-spacing:-.01em; }
h2{ font-size:15pt; margin:22pt 0 6pt; padding-top:8pt; border-top:2px solid var(--line);
  page-break-after:avoid; }
h3{ font-size:12pt; margin:14pt 0 4pt; color:var(--green); page-break-after:avoid; }
h4{ font-size:10.5pt; margin:10pt 0 3pt; }
p{ margin:0 0 7pt; }
a{ color:var(--green); text-decoration:none; }
strong{ color:#15201b; }
code{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:9pt;
  background:var(--surf); padding:1px 4px; border-radius:3px; }
pre{ background:var(--surf); border:1px solid var(--line); border-radius:6px;
  padding:10px 12px; overflow:auto; font-size:8.5pt; line-height:1.4;
  white-space:pre-wrap; }
pre code{ background:none; padding:0; }
table{ border-collapse:collapse; width:100%; margin:8pt 0 12pt; font-size:9pt;
  font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  page-break-inside:avoid; }
th,td{ border:1px solid var(--line); padding:4px 8px; text-align:left; vertical-align:top; }
th{ background:var(--surf); font-weight:600; }
img{ max-width:78%; height:auto; display:block; margin:10pt auto 2pt; page-break-inside:avoid; }
/* image captions: italic paragraph immediately after a figure */
img + em, p > em:only-child{ }
em{ color:var(--muted); }
hr{ border:none; border-top:1px solid var(--line); margin:14pt 0; }
ul,ol{ margin:0 0 7pt; padding-left:18px; }
li{ margin:0 0 3pt; }
blockquote{ margin:8pt 0; padding:2pt 12pt; border-left:3px solid var(--line);
  color:var(--muted); }
h2,h3{ string-set: none; }
"""

def main():
    text = SRC.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "attr_list", "sane_lists", "toc", "smarty"],
        output_format="html5",
    )
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Colmena vs. the Field — Whitepaper</title>
<style>{CSS}</style></head>
<body><div class="wrap">
{html_body}
</div></body></html>"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT} ({len(doc):,} bytes)")

if __name__ == "__main__":
    main()
