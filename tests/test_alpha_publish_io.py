from __future__ import annotations

import fcntl
import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

from scripts import alpha_publish_io as io


def _append_row_in_process(path: str, row_id: int, delay: float) -> None:
    def mutate(rows: list[Any]) -> bool:
        time.sleep(delay)
        rows.append({"id": row_id})
        return True

    io.update_json_list(Path(path), mutate)


def test_write_json_uses_sidecar_lock(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    io.write_json(tmp_path / "state.json", {"b": 2, "a": 1})

    assert calls == [("state.json.lock", fcntl.LOCK_EX)]
    assert json.loads((tmp_path / "state.json").read_text()) == {"a": 1, "b": 2}
    assert not (tmp_path / "state.json.tmp").exists()


def test_read_json_uses_sidecar_shared_lock(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")

    def fake_flock(handle: Any, op: int) -> None:
        calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)

    assert io.read_json(path, {}) == {"a": 1}
    assert calls == [("state.json.lock", fcntl.LOCK_SH)]


def test_write_text_uses_sidecar_lock(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    io.write_text(tmp_path / "state.md", "# State\n")

    assert calls == [("state.md.lock", fcntl.LOCK_EX)]
    assert (tmp_path / "state.md").read_text() == "# State\n"
    assert not (tmp_path / "state.md.tmp").exists()


def test_update_json_list_locks_and_only_writes_on_change(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    calls: list[tuple[str, int]] = []
    path = tmp_path / "rows.json"
    path.write_text(json.dumps([{"id": 1}]), encoding="utf-8")

    def fake_flock(handle: Any, op: int) -> None:
        calls.append((Path(handle.name).name, op))

    def append_row(rows: list[Any]) -> bool:
        rows.append({"id": 2})
        return True

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    changed = io.update_json_list(path, append_row)

    assert changed is True
    assert calls == [("rows.json.lock", fcntl.LOCK_EX)]
    assert json.loads(path.read_text()) == [{"id": 1}, {"id": 2}]

    changed = io.update_json_list(path, lambda _rows: False)
    assert changed is False
    assert json.loads(path.read_text()) == [{"id": 1}, {"id": 2}]


def test_update_json_list_preserves_parallel_writers(tmp_path: Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text("[]", encoding="utf-8")
    processes = [
        mp.Process(target=_append_row_in_process, args=(str(path), 1, 0.05)),
        mp.Process(target=_append_row_in_process, args=(str(path), 2, 0.0)),
    ]

    for proc in processes:
        proc.start()
    for proc in processes:
        proc.join(3)
    for proc in processes:
        if proc.is_alive():
            proc.terminate()
            proc.join(1)

    assert [proc.exitcode for proc in processes] == [0, 0]
    assert {row["id"] for row in json.loads(path.read_text())} == {1, 2}


def test_write_ledger_adds_publish_summary(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    io.write_ledger(path, {
        "status": "no_fresh_candidate",
        "submitted": 0,
        "published": 0,
        "considered": [{"status": "duplicate_submission_fingerprint"}],
        "cycle_attempts": [],
    })

    data = json.loads(path.read_text())
    assert data["publish_summary"]["status"] == "no_fresh_candidate"
    assert data["publish_summary"]["top_blockers"] == {
        "duplicate_submission_fingerprint": 1,
    }


def test_write_ledger_uses_sidecar_lock(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []

    def fake_flock(handle: Any, op: int) -> None:
        calls.append((Path(handle.name).name, op))

    monkeypatch.setattr(fcntl, "flock", fake_flock)
    io.write_ledger(tmp_path / "daily.json", {"status": "published"})

    assert calls == [("daily.json.lock", fcntl.LOCK_EX)]
