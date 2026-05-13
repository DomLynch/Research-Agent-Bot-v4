"""Sprint 20 — human-audit mini layer.

Per-run JSON overlay capturing human decisions on Sprint-18 sentinel-
repair entries + Sprint-19 needs_human_audit extraction flags. Lives at
`runs/<paper-dir>/manual_audit.json`; operator hand-edits it.

Overlay cannot promote into the primary set (sole purview of the
EvidenceEligibilityContract); it only records audit-trail decisions on
flagged items. Universal: no domain literals.

Schema:
  {"audits": [
    {"kind": "extraction", "study_id": "s01",
     "action": "approve|reject|correct", "reviewer": "...", "notes": "..."},
    {"kind": "sentinel", "sentinel_id": "10.1/x",
     "action": "uploaded|excluded|deferred", "reviewer": "...", "notes": "..."}
  ]}
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KINDS: frozenset[str] = frozenset({"extraction", "sentinel"})
_EXTRACTION_ACTIONS: frozenset[str] = frozenset({"approve", "reject", "correct"})
_SENTINEL_ACTIONS: frozenset[str] = frozenset({"uploaded", "excluded", "deferred"})


@dataclass(frozen=True, slots=True)
class ManualAuditEntry:
    kind: str
    target_id: str
    action: str
    reviewer: str
    notes: str


@dataclass(frozen=True, slots=True)
class ManualAuditOverlay:
    entries: tuple[ManualAuditEntry, ...]

    @property
    def k_total(self) -> int:
        return len(self.entries)

    def approved_extractions(self) -> frozenset[str]:
        return frozenset(
            e.target_id for e in self.entries
            if e.kind == "extraction" and e.action == "approve"
        )

    def resolved_sentinels(self) -> frozenset[str]:
        """Sentinels the human has acted on (uploaded / excluded /
        deferred) — drop them from the repair plan."""
        return frozenset(
            e.target_id for e in self.entries if e.kind == "sentinel"
        )


def _parse_entry(raw: dict[str, object]) -> ManualAuditEntry | None:
    kind = str(raw.get("kind") or "").strip()
    if kind not in _KINDS:
        return None
    target = str(raw.get("study_id") or raw.get("sentinel_id") or "").strip()
    action = str(raw.get("action") or "").strip()
    if not target or not action:
        return None
    allowed = _EXTRACTION_ACTIONS if kind == "extraction" else _SENTINEL_ACTIONS
    if action not in allowed:
        return None
    return ManualAuditEntry(
        kind=kind, target_id=target, action=action,
        reviewer=str(raw.get("reviewer") or ""),
        notes=str(raw.get("notes") or ""),
    )


def load_manual_audit(run_dir: Path) -> ManualAuditOverlay:
    """Parse `manual_audit.json` if present. Missing file / malformed
    JSON returns an empty overlay; never raises."""
    path = run_dir / "manual_audit.json"
    if not path.exists():
        return ManualAuditOverlay(entries=())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ManualAuditOverlay(entries=())
    raw = data.get("audits") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return ManualAuditOverlay(entries=())
    parsed = [e for r in raw if isinstance(r, dict)
              for e in (_parse_entry(r),) if e is not None]
    return ManualAuditOverlay(entries=tuple(parsed))
