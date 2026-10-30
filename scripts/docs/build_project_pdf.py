#!/usr/bin/env python3
"""Build the repository's curated Markdown documents into one XeLaTeX PDF."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "docs" / "latex"
MANIFEST_PATH = MODULE / "manifest.toml"
OUTPUT_DIR = ROOT / ".artifacts" / "docs-pdf"
PUBLIC_MANIFEST = ROOT / "product_docs" / "manifest.json"
DENIED_PATH_PARTS = {
    ".workspace",
    "audits",
    "grill",
    "research-decision-graph",
    "sources",
}


class BuildError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path = ROOT, capture: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )
    if result.returncode:
        output = result.stdout or ""
        raise BuildError(f"command failed ({result.returncode}): {' '.join(args)}\n{output}")
    return result.stdout or ""


def tracked_path(relative: str) -> Path:
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BuildError(f"path escapes repository root: {relative}") from exc
    parts = Path(relative).parts
    if any(part in DENIED_PATH_PARTS for part in parts):
        raise BuildError(f"restricted document path is not allowed: {relative}")
    if relative != "README.md" and not (
        relative.startswith("docs/") or relative.startswith("product_docs/")
    ):
        raise BuildError(f"document source must be under docs/ or product_docs/: {relative}")
    if candidate.suffix.lower() not in {".md", ".tex"}:
        raise BuildError(f"unsupported document source type: {relative}")
    if not candidate.is_file():
        raise BuildError(f"document source does not exist: {relative}")
    return candidate


def load_manifest() -> dict[str, Any]:
    try:
        manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"cannot read {MANIFEST_PATH.relative_to(ROOT)}: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise BuildError("manifest schema_version must be 1")
    if (
        not manifest.get("title")
        or not manifest.get("edition")
        or not isinstance(manifest.get("sections"), list)
        or not isinstance(manifest.get("changes"), list)
        or not manifest["changes"]
    ):
        raise BuildError("manifest requires title, edition, sections, and version changes")
    for change in manifest["changes"]:
        if not all(change.get(key) for key in ("version", "date", "summary")):
            raise BuildError("each change entry requires version, date, and summary")
    section_ids: set[str] = set()
    source_paths: set[str] = set()
    document_slugs: set[str] = set()
    documents = 0
    for section in manifest["sections"]:
        section_id = section.get("id")
        if not section_id or section_id in section_ids:
            raise BuildError(f"missing or duplicate section id: {section_id!r}")
        section_ids.add(section_id)
        if not section.get("title") or not section.get("audience") or not section.get("purpose"):
            raise BuildError(f"section {section_id!r} needs title, audience, and purpose")
        entries = section.get("documents", [])
        if not entries:
            raise BuildError(f"section {section_id!r} has no documents")
        for entry in entries:
            source = entry.get("source")
            if not entry.get("title") or not source:
                raise BuildError(f"document in {section_id!r} needs title and source")
            if source in source_paths:
                raise BuildError(f"duplicate document source: {source}")
            source_paths.add(source)
            tracked_path(source)
            slug = entry.get("slug")
            if slug:
                if slug in document_slugs:
                    raise BuildError(f"duplicate PDF document slug: {slug}")
                document_slugs.add(slug)
            documents += 1
    if documents == 0:
        raise BuildError("manifest must contain at least one document")
    return manifest


def public_doc_paths() -> dict[str, tuple[str, ...]]:
    """Return source-to-code-path metadata from the existing public docs registry."""
    try:
        data = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read public documentation manifest: {exc}") from exc
    result: dict[str, tuple[str, ...]] = {}
    for section in data.get("sections", []):
        for page in section.get("pages", []):
            source = f"product_docs/{page['source']}"
            paths = tuple(page.get("canonical_paths", []))
            if paths:
                result[source] = paths
    return result


def git_source_date(source: str) -> tuple[str, bool]:
    try:
        latest = run(["git", "log", "-1", "--format=%cs", "HEAD", "--", source]).strip()
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", source], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
        changed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", source], cwd=ROOT, check=False,
        ).returncode != 0
    except BuildError:
        return "Git 日期不可用", True
    if not tracked or not latest:
        return "未提交到 Git", True
    if changed:
        return f"工作区有未提交修改（HEAD 版本 {latest}）", True
    return latest, False


def repository_snapshot_identity() -> str:
    """Identify HEAD plus all tracked and non-ignored untracked worktree content."""
    head = run(["git", "rev-parse", "--short=12", "HEAD"]).strip()
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if diff.returncode:
        raise BuildError("cannot fingerprint tracked worktree changes: " + diff.stderr.decode("utf-8", "replace"))
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if untracked.returncode:
        raise BuildError("cannot list untracked worktree files: " + untracked.stderr.decode("utf-8", "replace"))
    digest = hashlib.sha256()
    digest.update(head.encode("ascii"))
    digest.update(diff.stdout)
    untracked_paths = [path for path in untracked.stdout.split(b"\0") if path]
    for raw_path in sorted(untracked_paths):
        path = ROOT / os.fsdecode(raw_path)
        if path.is_file():
            digest.update(raw_path)
            digest.update(b"\0")
            digest.update(path.read_bytes())
    if not diff.stdout and not untracked_paths:
        return head
    return f"{head}+dirty.{digest.hexdigest()[:12]}"


def remove_leading_title(markdown: str) -> str:
    # The manifest title is canonical; source H1s would otherwise duplicate it.
    text = markdown.lstrip("\ufeff")
    front_matter = re.match(r"\A---\s*\n.*?\n---\s*\n", text, flags=re.DOTALL)
    if front_matter:
        text = text[front_matter.end():]
    return re.sub(r"\A\s*#\s+[^\n]+\n+", "", text, count=1)


def normalize_fenced_code(markdown: str) -> str:
    """Keep code blocks readable without relying on Pandoc/listings language aliases."""
    text = re.sub(
        r"^(\s{0,3}(?:`{3,}|~{3,}))[A-Za-z0-9_+.-]+[^\n]*$",
        r"\1",
        markdown,
        flags=re.MULTILINE,
    )
    # Latin monospaced fonts do not consistently contain box-drawing glyphs.
    return text.translate(str.maketrans({"├": "+", "└": "+", "┬": "+", "┴": "+", "┼": "+", "─": "-", "│": "|"}))


def normalize_status_symbols(markdown: str) -> str:
    """Use readable text labels for status glyphs missing from common PDF fonts."""
    return (
        markdown.replace("✅", "[通过]")
        .replace("❌", "[失败]")
        .replace("⚠️", "[注意]")
        .replace("⚠", "[注意]")
    )


def normalize_inline_code(latex: str) -> str:
    """Replace Pandoc's listings passthrough wrapper with robust texttt markup."""
    marker = r"\passthrough{\lstinline"
    cursor = 0
    chunks: list[str] = []
    while True:
        start = latex.find(marker, cursor)
        if start < 0:
            chunks.append(latex[cursor:])
            break
        chunks.append(latex[cursor:start])
        delimiter_at = start + len(marker)
        if delimiter_at >= len(latex):
            raise BuildError("malformed Pandoc inline-code passthrough")
        delimiter = latex[delimiter_at]
        close = latex.find(delimiter, delimiter_at + 1)
        if close < 0 or close + 1 >= len(latex) or latex[close + 1] != "}":
            raise BuildError("malformed Pandoc inline-code delimiter")
        inline_code = latex[delimiter_at + 1:close]
        # Give long paths and hashes legal breakpoints without changing their text.
        inline_code = re.sub(r"(?<!\\)([$%&#{}])", r"\\\1", inline_code)
        inline_code = inline_code.replace("≡", r"\ensuremath{\equiv}")
        inline_code = re.sub(r"(\\[_%#{}])", r"\1\\allowbreak{}", inline_code)
        inline_code = re.sub(r"(?<!\\)([/.:_-])", r"\1\\allowbreak{}", inline_code)
        if re.fullmatch(r"[0-9a-fA-F]{32,}", inline_code):
            inline_code = "\\allowbreak{}".join(
                inline_code[index:index + 8]
                for index in range(0, len(inline_code), 8)
            )
        chunks.append("\\texttt{" + inline_code + "}")
        cursor = close + 2
    return "".join(chunks).replace(r"\def\LTcaptype{none}", r"\def\LTcaptype{}")


def namespace_source_anchors(markdown: str, slug: str) -> str:
    """Avoid collisions between identical section ids in different source files."""
    markdown = re.sub(
        r"\{#([A-Za-z][A-Za-z0-9_.:-]*)\}",
        lambda match: "{#" + slug + "-" + match.group(1) + "}",
        markdown,
    )
    return re.sub(
        r"(?<=\]\(#)(?!doc-)([A-Za-z][A-Za-z0-9_.:-]*)(?=\))",
        lambda match: slug + "-" + match.group(1),
        markdown,
    )


def rewrite_registered_links(
    markdown: str,
    source: str,
    source_to_slug: dict[str, str],
    public_slug_to_source: dict[str, str],
) -> str:
    """Route known in-bundle links to stable chapter anchors."""
    link_pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")

    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("https://", "http://", "mailto:", "#")):
            return match.group(0)
        raw_target, separator, fragment = target.partition("#")
        public = re.match(r"/docs/([a-z0-9-]+)$", raw_target)
        if public:
            target_source = public_slug_to_source.get(public.group(1))
        else:
            raw_path = raw_target
            if not raw_path:
                return match.group(0)
            resolved = (ROOT / source).parent.joinpath(raw_path).resolve()
            try:
                target_source = resolved.relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                target_source = None
        slug = source_to_slug.get(target_source or "")
        if not slug:
            return f"{label}（`{target}`）"
        anchor = f"{slug}-{fragment}" if separator and fragment and not fragment.startswith("doc-") else f"doc-{slug}"
        return f"[{label}](#{anchor})"

    return link_pattern.sub(replace, markdown)


def collect_chapters(manifest: dict[str, Any]) -> tuple[str, list[str], int]:
    public_paths = public_doc_paths()
    product_doc_index = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
    public_slug_to_source = {
        page["slug"]: f"product_docs/{page['source']}"
        for section in product_doc_index.get("sections", [])
        for page in section.get("pages", [])
    }
    docs = [
        (section, entry)
        for section in manifest["sections"]
        for entry in section["documents"]
    ]
    source_to_slug = {
        entry["source"]: entry.get("slug", f"source-{index:03d}")
        for index, (_, entry) in enumerate(docs, start=1)
    }
    output: list[str] = []
    warnings: list[str] = []
    for section in manifest["sections"]:
        output.append(f"\\part{{{section['title']}}}\n")
        for entry in section["documents"]:
            source = entry["source"]
            source_path = tracked_path(source)
            freshness, modified = git_source_date(source)
            if modified:
                warnings.append(f"source is modified or untracked: {source}")
            for implementation_path in public_paths.get(source, ()):
                if not (ROOT / implementation_path).exists():
                    raise BuildError(
                        f"canonical implementation path missing for {source}: {implementation_path}"
                    )
            if source_path.suffix.lower() == ".tex":
                body = source_path.read_text(encoding="utf-8")
            else:
                body = source_path.read_text(encoding="utf-8")
                body = remove_leading_title(body)
                body = normalize_fenced_code(body)
                body = normalize_status_symbols(body)
                body = namespace_source_anchors(body, source_to_slug[source])
                body = rewrite_registered_links(
                    body, source, source_to_slug, public_slug_to_source
                )
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            slug = source_to_slug[source]
            output.extend([
                f"# {entry['title']} {{#doc-{slug}}}\n",
                "> **适用读者：** " + section["audience"] + "  \n"
                + "> **本章用途：** " + section["purpose"] + "  \n"
                + f"> **源文档：** `{source}`  \n"
                + f"> **源文档最后修改：** {freshness}  \n"
                + f"> **源文档 SHA-256：** `{source_hash}`\n",
                body.strip(),
                "\n\n",
            ])
    return "\n".join(output), warnings, len(docs)


def tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in text)


def write_metadata(
    manifest: dict[str, Any],
    output_dir: Path,
    revision: str,
    build_date: str,
    toolchain: tuple[str, str, str],
) -> None:
    edition = os.environ.get("TR_DOCS_EDITION", str(manifest["edition"]))
    changed_docs = sum(len(section["documents"]) for section in manifest["sections"])
    changes = manifest.get("changes", [])
    if not changes:
        raise BuildError("manifest must contain at least one version change entry")
    change_items = "\n".join(
        "\\item \\textbf{" + tex_escape(str(item["version"])) + " ("
        + tex_escape(str(item["date"])) + ")}：" + tex_escape(str(item["summary"]))
        for item in changes
    )
    summary = (
        "\\begin{itemize}\n"
        + f"\\item 当前文档版本：\\textbf{{{tex_escape(edition)}}}，"
        + f"基于源码快照 \\texttt{{{tex_escape(revision)}}}。\n"
        + f"\\item 显式登记 {changed_docs} 份文档源；每份正文历史以其源文件 Git 记录为准。\n"
        + change_items
        + "\n\\end{itemize}"
    )
    toolchain_summary = "；".join(toolchain)
    metadata = (
        f"\\newcommand{{\\DocEdition}}{{{tex_escape(edition)}}}\n"
        f"\\newcommand{{\\DocBuildRevision}}{{\\texttt{{{tex_escape(revision)}}}}}\n"
        f"\\newcommand{{\\DocBuildDate}}{{{tex_escape(build_date)}}}\n"
        f"\\newcommand{{\\DocChangeSummary}}{{{summary}}}\n"
        f"\\newcommand{{\\DocToolchain}}{{{tex_escape(toolchain_summary)}}}\n"
    )
    (output_dir / "metadata.tex").write_text(metadata, encoding="utf-8")


def check_tools(pandoc_override: Path | None = None) -> tuple[str, str, str, str]:
    pandoc = str(pandoc_override) if pandoc_override else os.environ.get("PANDOC") or shutil.which("pandoc")
    latexmk = shutil.which("latexmk")
    xelatex = shutil.which("xelatex")
    missing = [name for name, value in (("pandoc", pandoc), ("latexmk", latexmk), ("xelatex", xelatex)) if not value]
    if missing:
        raise BuildError("missing required document tools: " + ", ".join(missing))
    pandoc_version = run([pandoc, "--version"]).splitlines()[0]
    latex_version = run([xelatex, "--version"]).splitlines()[0]
    latexmk_version = run([latexmk, "-v"]).splitlines()[0]
    return pandoc, pandoc_version, latex_version, latexmk_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the manifest and sources only")
    parser.add_argument("--output", type=Path, help="PDF output path (default: .artifacts/docs-pdf/TradeResearch-project-docs.pdf)")
    parser.add_argument("--pandoc", type=Path, help="Pandoc executable (default: PATH or PANDOC environment variable)")
    parser.add_argument("--keep-intermediates", action="store_true", help="keep generated Markdown, TeX, and LaTeX logs for debugging")
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        content, warnings, count = collect_chapters(manifest)
        revision = repository_snapshot_identity()
        print(f"manifest: {len(manifest['sections'])} sections, {count} documents")
        print(f"source revision: {revision}")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if args.check:
            print("document manifest check: passed")
            return 0

        pandoc, pandoc_version, xelatex_version, latexmk_version = check_tools(args.pandoc)
        output = (args.output or (OUTPUT_DIR / "TradeResearch-project-docs.pdf")).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
        if source_date_epoch:
            build_date = dt.datetime.fromtimestamp(
                int(source_date_epoch), tz=dt.timezone.utc
            ).date().isoformat()
        else:
            build_date = dt.date.today().isoformat()
        write_metadata(manifest, OUTPUT_DIR, revision, build_date, (
            pandoc_version, xelatex_version, latexmk_version
        ))
        chapter_markdown = OUTPUT_DIR / "chapters.md"
        chapter_tex = OUTPUT_DIR / "chapters.tex"
        chapter_markdown.write_text(content, encoding="utf-8")
        resource_roots = [str(ROOT)]
        for section in manifest["sections"]:
            for entry in section["documents"]:
                resource_roots.append(str((ROOT / entry["source"]).parent))
        print(f"Pandoc: {pandoc_version}")
        print(f"XeLaTeX: {xelatex_version}")
        print(f"latexmk: {latexmk_version}")
        run([
            pandoc, str(chapter_markdown), "--from=markdown+raw_tex+pipe_tables+task_lists",
            "--to=latex", "--top-level-division=chapter", "--listings",
            "--resource-path=" + os.pathsep.join(dict.fromkeys(resource_roots)),
            "--output", str(chapter_tex),
        ])
        chapter_tex.write_text(
            normalize_inline_code(chapter_tex.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        run([
            shutil.which("latexmk") or "latexmk", "-C",
            f"-outdir={OUTPUT_DIR}", str(MODULE / "main.tex"),
        ])
        run([
            shutil.which("latexmk") or "latexmk", "-xelatex", "-halt-on-error",
            "-interaction=nonstopmode", f"-outdir={OUTPUT_DIR}",
            str(MODULE / "main.tex"),
        ])
        compiled = OUTPUT_DIR / "main.pdf"
        if not compiled.is_file():
            raise BuildError(f"LaTeX succeeded but output was not found: {compiled}")
        final_revision = repository_snapshot_identity()
        if final_revision != revision:
            raise BuildError(
                "repository changed while the PDF was building; rerun against a stable snapshot "
                f"(before={revision}, after={final_revision})"
            )
        if compiled.resolve() != output:
            shutil.copy2(compiled, output)
        print(f"PDF: {output}")
        print(f"size: {output.stat().st_size} bytes")
        if not args.keep_intermediates:
            run([
                shutil.which("latexmk") or "latexmk", "-c",
                f"-outdir={OUTPUT_DIR}", str(MODULE / "main.tex"),
            ])
            for intermediate in (chapter_markdown, chapter_tex, OUTPUT_DIR / "metadata.tex"):
                if intermediate.exists():
                    intermediate.unlink()
            if compiled.resolve() != output:
                compiled.unlink(missing_ok=True)
        return 0
    except (BuildError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
