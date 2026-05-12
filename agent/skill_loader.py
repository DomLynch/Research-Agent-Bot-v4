"""Markdown-skill loader (ARIS-pattern, minimal).

Externalises long-form prompts from Python triple-quoted literals to
`.md` files under `topic_packs/skills/`. Each skill file has YAML
frontmatter (`---name: ...\\n---`) followed by the prompt body. The
loader returns just the body, stripped of frontmatter.

Why: prompt content edits become topic-pack data changes (not code
changes); the same loader can serve per-topic prompt variants in a
later sprint by accepting `(skill_name, topic_pack)` keys. This is the
proof of pattern; agent/prompts.py SYSTEM_WRITER is migrated as the
first skill so future migrations have a working template.

Universal: nothing biomedical or topic-specific in the loader. Skills
live in data; the loader is topic-agnostic.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "topic_packs" / "skills"


@lru_cache(maxsize=64)
def load_skill(name: str) -> str:
    """Return the prompt body of `topic_packs/skills/<name>.md`.

    Frontmatter (everything between the leading `---` line and the next
    `---` line) is stripped. Raises FileNotFoundError if the skill is
    missing — callers should never silently fall back, because a missing
    prompt is a deployment bug, not an edge case.
    """
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"skill not found: {path}")
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            text = text[end + 4 :]
    return text.lstrip("\n")
