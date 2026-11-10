#!/usr/bin/env python3
"""Preflight the channels and strategy interface of a proposed worker release.

Example (from the PR checkout, before sending either release message):
  python bin/check-release-pair.py --base origin/main --send plumbing --send bench \
    --plumbing-source /path/to/plumbing/factory/run.py \
    --bench-source /path/to/bench/bin/strategy

Use the actual proposed release files, not merely the PR checkout. A root
Markdown change is reported as a bench cache impact if later packaged, but
does not require a bench send when the existing bench pin is intentionally kept.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


BENCH_ROOTS = {"bin", "cases", "guards", "harbor", "projects", "scenarios"}


def required_channels(paths: list[str]) -> set[str]:
    channels = set()
    for path in paths:
        parts = Path(path).parts
        if not parts:
            continue
        if parts[0] == "factory":
            channels.add("plumbing")
        elif parts[0] in BENCH_ROOTS and path != "bin/check-release-pair.py":
            channels.add("bench")
    return channels


def bench_document_changes(paths: list[str]) -> list[str]:
    # Root Markdown is bench content when packaged, but a plumbing-only release can
    # deliberately keep the current bench pin and its gate bindings unchanged.
    return [path for path in paths if len(Path(path).parts) == 1 and path.endswith(".md")]


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    result = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "--no-renames",
                             f"{base}...{head}"], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def check_strategy_interface(plumbing_source: Path, bench_source: Path) -> None:
    """Check the actual run.py call against the actual strategy simulate signature."""
    run = ast.parse(plumbing_source.read_text(), filename=str(plumbing_source))
    strategy = ast.parse(bench_source.read_text(), filename=str(bench_source))
    calls = [node for node in ast.walk(run) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "simulate"
             and isinstance(node.func.value, ast.Name) and node.func.value.id == "module"]
    definitions = [node for node in strategy.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == "simulate"]
    if len(calls) != 1 or len(definitions) != 1:
        raise ValueError("expected one module.simulate call and one strategy simulate definition")
    call, definition = calls[0], definitions[0]
    positional = definition.args.posonlyargs + definition.args.args
    accepted = {arg.arg for arg in positional + definition.args.kwonlyargs}
    if any(isinstance(arg, ast.Starred) for arg in call.args):
        raise ValueError("strategy simulate call has dynamic positional arguments")
    if len(call.args) > len(positional) and definition.args.vararg is None:
        raise ValueError("strategy simulate accepts fewer positional arguments than run.py passes")
    for keyword in call.keywords:
        if keyword.arg is None:
            raise ValueError("strategy simulate call has dynamic keyword arguments")
        if keyword.arg not in accepted and definition.args.kwarg is None:
            raise ValueError(f"strategy simulate does not accept {keyword.arg}=")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    paths = parser.add_mutually_exclusive_group(required=True)
    paths.add_argument("--base", help="compare this Git ref with --head to read the full PR diff")
    paths.add_argument("--changed-file", action="append",
                       help="one path from a reviewed manifest; repeat for every changed file")
    parser.add_argument("--head", default="HEAD", help="Git head used with --base (default: HEAD)")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Git checkout used with --base")
    parser.add_argument("--send", action="append", choices=("plumbing", "bench"), default=[],
                        help="release channel planned for this batch; repeat if both are planned")
    parser.add_argument("--plumbing-source", type=Path, required=True,
                        help="factory/run.py from the actual plumbing release")
    parser.add_argument("--bench-source", type=Path, required=True,
                        help="bin/strategy from the actual bench release")
    args = parser.parse_args(argv)
    try:
        files = changed_files(args.repo, args.base, args.head) if args.base else args.changed_file
    except subprocess.CalledProcessError as error:
        print("cannot read PR diff: " + error.stderr.strip(), file=sys.stderr)
        return 1
    if not files:
        print("empty PR diff or manifest", file=sys.stderr)
        return 1
    required = required_channels(files)
    print("required channels: " + (", ".join(sorted(required)) or "none"))
    documents = bench_document_changes(files)
    if documents:
        print("bench documents changed: " + ", ".join(sorted(documents))
              + "; sending them in a bench release changes judge/gate cache bindings")
    missing = required - set(args.send)
    if missing:
        print("missing release channel: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 1
    try:
        check_strategy_interface(args.plumbing_source, args.bench_source)
    except (OSError, SyntaxError, ValueError) as error:
        print("incompatible release pair: " + str(error), file=sys.stderr)
        return 1
    print("strategy interface: compatible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
