"""Markdown cleanup helpers for alpha submission payloads."""
from __future__ import annotations

import re


def drop_markdown_section(memo: str, heading: str) -> str:
    out: list[str] = []
    dropping = False
    for line in memo.splitlines():
        if line.strip() == heading:
            dropping = True
            continue
        if dropping and line.startswith("## "):
            dropping = False
        if not dropping:
            out.append(line)
    return "\n".join(out)


def plain_section(memo: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n+(.*?)(?=^## |\Z)", memo, re.M | re.S)
    if not match:
        return ""
    text = re.sub(r"`([^`]+)`", r"\1", match.group(1))
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    lines = [
        re.sub(r"^[-*]\s+", "", line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("|")
    ]
    return " ".join(" ".join(lines).split())


def safe_excerpt(text: str, limit: int = 1200) -> str:
    excerpt = " ".join(str(text or "").split())
    if re.fullmatch(r"(?i)(abstract:|review summary:)?\s*alpha memo(?:\s*[—-]\s*[\w -]+)?\.?", excerpt):
        return ""
    sentence_cuts = [
        match.end()
        for match in re.finditer(r"[.!?](?=\s|$)", excerpt[:limit + 1])
    ]
    if len(excerpt) <= limit:
        if sentence_cuts:
            return excerpt[:sentence_cuts[-1]]
        return ""
    if sentence_cuts:
        return excerpt[:sentence_cuts[-1]]
    return ""


def public_submission_markdown(memo: str) -> str:
    memo = drop_markdown_section(memo, "## Provenance / priority")
    memo = drop_markdown_section(memo, "## Next extraction")
    memo = drop_markdown_section(memo, "## Subtopic recommendations")
    internal_prefixes = (
        "# Alpha memo",
        "**Headline:**",
        "**Alpha score:**",
        "**Alpha triage:**",
        "**Confidence:**",
        "**Memo surface:**",
        "**Snapshot:**",
        "**Run:**",
        "**Direct source breadth:**",
        "**Source thesis:**",
        "**Source breadth:**",
    )
    internal_markers = ("Frontier review skipped", "deterministic gate audit")
    lines = [
        line for line in memo.splitlines()
        if not line.startswith(internal_prefixes)
        and not any(marker in line for marker in internal_markers)
    ]
    text = "\n".join(lines).strip() + "\n"
    note = (
        "**Interpretation note:** This is a hypothesis-generating alpha memo, "
        "not confirmatory evidence; subgroup or context-derived claims require "
        "independent replication.\n"
    )
    if "## Why this is surprising" in text and note not in text:
        text = text.replace("\n## Why this is surprising", f"\n\n{note}\n## Why this is surprising", 1)
    return text.replace(
        "## Context receipts\n\n",
        "## Context receipts\n\n"
        "_Boundary evidence only; these receipts broaden source context but do "
        "not independently prove the lead claim._\n\n",
    )


def raw_section(memo: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n+(.*?)(?=^## |\Z)", memo, re.M | re.S)
    if not match:
        return ""
    return re.sub(r"\s*`?fact_id=[A-Za-z0-9_-]+`?\s*", " ", match.group(1)).strip()
