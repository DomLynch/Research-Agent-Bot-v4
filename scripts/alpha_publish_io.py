"""Locked JSON IO helpers for alpha publish runtime state."""
from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

Json = dict[str, Any]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    tmp_path = path.with_name(path.name + ".tmp")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8",
        )
        tmp_path.replace(path)


def update_json_list(path: Path, mutate: Callable[[list[Any]], bool]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    tmp_path = path.with_name(path.name + ".tmp")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = []
        rows = data if isinstance(data, list) else []
        changed = mutate(rows)
        if changed:
            tmp_path.write_text(
                json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8",
            )
            tmp_path.replace(path)
        return changed


def write_ledger(path: Path, ledger: Json) -> None:
    write_json(path, ledger)
