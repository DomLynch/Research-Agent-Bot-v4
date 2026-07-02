#!/usr/bin/env python3
"""Smoke-check source-lit guide anchors against the public surface."""
from __future__ import annotations

import importlib
import inspect
import re
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PUBLIC_MODULE = "research_agent_bot_v4.source_lit"
GUIDE_GLOBS = (
    "docs/source-lit/**/*.md",
    "docs/source_lit/**/*.md",
    "docs/*source-lit*.md",
)
ANCHOR_RE = re.compile(r"^\s*-\s*`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`(?:\s|:|-|$)")


def _ensure_import_path() -> None:
    for path in (ROOT, SRC):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _guide_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in GUIDE_GLOBS:
        paths.update(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def _guide_anchors(paths: list[Path]) -> dict[str, list[tuple[Path, int]]]:
    refs: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    for path in paths:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = ANCHOR_RE.match(line)
            if match:
                refs[match.group("name")].append((path, line_no))
    return dict(refs)


def _public_surface() -> ModuleType:
    _ensure_import_path()
    return importlib.import_module(PUBLIC_MODULE)


def _location_text(locations: list[tuple[Path, int]]) -> str:
    return ", ".join(f"{path.relative_to(ROOT)}:{line_no}" for path, line_no in locations)


def _is_live_anchor(value: object) -> bool:
    return inspect.isfunction(value) or inspect.isclass(value)


def main() -> int:
    guides = _guide_paths()
    if not guides:
        print("MISSING: no source-lit guide docs found under docs/source-lit/ or docs/source_lit/")
        return 1

    refs = _guide_anchors(guides)
    if not refs:
        print("MISSING: no source-lit anchors found in guide bullets like '- `fetch_papers`'.")
        return 1

    try:
        surface = _public_surface()
    except Exception as exc:
        print(f"MISSING: cannot import {PUBLIC_MODULE}: {exc}")
        return 1

    missing: list[tuple[str, list[tuple[Path, int]]]] = []
    wrong_kind: list[tuple[str, list[tuple[Path, int]], str]] = []
    for name, locations in sorted(refs.items()):
        if not hasattr(surface, name):
            missing.append((name, locations))
            continue
        value = getattr(surface, name)
        if not _is_live_anchor(value):
            wrong_kind.append((name, locations, type(value).__name__))

    if missing or wrong_kind:
        print("Missing or renamed source-lit public anchors:")
        for name, locations in missing:
            print(f"- {name}: referenced at {_location_text(locations)}")
        for name, locations, kind in wrong_kind:
            print(f"- {name}: referenced at {_location_text(locations)} but resolves to {kind}")
        exported = getattr(surface, "__all__", ())
        if exported:
            print("Available public anchors: " + ", ".join(sorted(str(name) for name in exported)))
        return 1

    print(f"OK: {len(refs)} source-lit anchors resolved from {len(guides)} guide(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
