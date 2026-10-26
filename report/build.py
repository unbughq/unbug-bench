#!/usr/bin/env python3
"""Rebuild report/index.html from template.html, data/*.json and fonts/ (OFL, embedded so the page works offline)."""
import base64, pathlib
here = pathlib.Path(__file__).parent
css = ""
for f in sorted((here / "fonts").glob("*.woff2")):
    fam = "Source Serif 4" if "serif" in f.name else "Source Sans 3"
    w, st = f.stem.split("-")[-2:]
    css += f'@font-face{{font-family:"{fam}";font-style:{st};font-weight:{w};font-display:swap;src:url(data:font/woff2;base64,{base64.b64encode(f.read_bytes()).decode()}) format("woff2")}}\n'
d = lambda n: (here / "data" / n).read_text().strip()
out = (here / "template.html").read_text().replace("__FONTS__", css).replace("__R1__", d("round1.json")) \
    .replace("__R2__", d("round2.json")).replace("__V2__", d("round2-unbug-v0.2.json") or "{}")
(here / "index.html").write_text(out)
print("wrote", here / "index.html", len(out), "bytes")
