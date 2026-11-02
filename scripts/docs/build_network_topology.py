"""Render the project topology for the web from the same TeX source as the PDF.

The generated SVGs contain paths, including the Font Awesome hardware icons,
so browsers need neither the TeX fonts nor a client-side diagram renderer.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/latex/network-topology.tex"
OUTPUT = ROOT / "static/vendor/web-app"


def render(output: Path) -> None:
    xelatex = shutil.which("xelatex")
    pdftocairo = os.environ.get("PDFTOCAIRO") or shutil.which("pdftocairo")
    if not xelatex or not pdftocairo:
        raise RuntimeError("xelatex and pdftocairo are required to render the topology")
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SOURCE_DATE_EPOCH": "1700000000", "FORCE_SOURCE_DATE": "1"}
    with tempfile.TemporaryDirectory(prefix="tr-topology-") as temp:
        directory = Path(temp)
        for language in ("zh", "en"):
            english = "\\def\\TREnglish{1}\n" if language == "en" else ""
            tex = (
                "\\documentclass[tikz,border=8pt]{standalone}\n"
                "\\usepackage[UTF8]{ctex}\n"
                "\\usepackage{fontawesome5}\n"
                "\\usetikzlibrary{arrows.meta,decorations.pathreplacing}\n"
                + english + "\\begin{document}\n"
                + f"\\input{{{SOURCE.as_posix()}}}\n"
                + "\\end{document}\n"
            )
            source = directory / f"topology-{language}.tex"
            source.write_text(tex, encoding="utf-8")
            compiled = subprocess.run(
                [xelatex, "-halt-on-error", "-interaction=nonstopmode", f"-output-directory={directory}", str(source)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if compiled.returncode:
                raise RuntimeError("topology TeX compilation failed:\n" + "\n".join(compiled.stdout.splitlines()[-25:]))
            generated = directory / f"network-topology.{language}.svg"
            subprocess.run(
                [pdftocairo, "-svg", str(directory / f"topology-{language}.pdf"), str(generated)],
                cwd=ROOT, env=env, check=True,
            )
            shutil.copyfile(generated, output / generated.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    render(args.output.resolve())


if __name__ == "__main__":
    main()
