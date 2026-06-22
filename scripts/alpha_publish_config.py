"""Config readers for alpha publish policy files."""
from __future__ import annotations

import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

Json = dict[str, Any]


def _toml(path: Path) -> Json:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def alpha_memo_int(path: Path, name: str, default: int) -> int:
    alpha = _toml(path).get("alpha_memo")
    if not isinstance(alpha, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(alpha.get(name))))
    return default


def domain_alpha_memo_int(path: Path, domain: str, name: str, default: int) -> int:
    alpha = _toml(path).get("alpha_memo")
    domains = alpha.get("domains") if isinstance(alpha, dict) else {}
    domain_cfg = domains.get(domain) if isinstance(domains, dict) else {}
    if not isinstance(domain_cfg, dict) or name not in domain_cfg:
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(domain_cfg.get(name))))
    return default


def alpha_memo_float(path: Path, name: str, default: float) -> float:
    alpha = _toml(path).get("alpha_memo")
    if not isinstance(alpha, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0.0, float(str(alpha.get(name))))
    return default


def alpha_memo_bool(path: Path, name: str, default: bool) -> bool:
    alpha = _toml(path).get("alpha_memo")
    if not isinstance(alpha, dict) or name not in alpha:
        return default
    return bool(alpha.get(name))


def publish_tier_int(path: Path, name: str, default: int) -> int:
    thresholds = _toml(path).get("thresholds")
    if not isinstance(thresholds, dict):
        return default
    with suppress(TypeError, ValueError):
        return max(0, int(str(thresholds.get(name))))
    return default
