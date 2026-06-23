"""Locked JSON IO helpers for alpha publish state."""
from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts import alpha_publish_status as publish_status

Json = dict[str, Any]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    tmp_path = path.with_name(path.name + ".tmp")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)


def update_json_list(path: Path, mutate: Callable[[list[Any]], bool]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    tmp_path = path.with_name(path.name + ".tmp")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_json(path, [])
        rows = data if isinstance(data, list) else []
        changed = mutate(rows)
        if changed:
            tmp_path.write_text(
                json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8",
            )
            tmp_path.replace(path)
        return changed


def write_ledger(path: Path, ledger: Json) -> None:
    ledger["publish_summary"] = publish_status.publish_summary(ledger)
    write_json(path, ledger)
