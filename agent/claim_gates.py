"""Deterministic gates that police LLM claims.

Pure regex + topic-pack lookups — no LLM, no extra agents. Each gate
returns a list of violations; empty means PASS. The runner decides whether
to report and abort, or feed violations back to the writer for retry.

Gates:
  1. evidence_slot          — every empirical sentence has a structured slot
  2. novelty_claim          — banned phrases that erase prior literature
  3. title_claim            — title must not assert a moderator conclusion
  4. citation_role          — every [CIT:key|role]; role in allowed list; anchor
                              keys carry their canonical role
  5. scope_consistency      — body must not use topic-pack discouraged terms
  6. anchor_role_in_prose   — prose calling 'X by Surname' must match the
                              anchor role for that surname

Topic-pack-driven gates (4-6) are no-ops when no pack is supplied — keeps
the basic gates topic-agnostic.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from agent.topic_pack import TopicPack


@dataclass(frozen=True, slots=True)
class GateViolation:
    gate: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# Generic slot pattern: [ALL_CAPS_TOKEN], optionally with :value or =value.
_SLOT_RE = re.compile(r"\[[A-Z][A-Z0-9_]*(?:\s*[:=][^\]]*)?\]")


# --- Evidence-slot triggers ------------------------------------------------
# Universal core: terms domain-agnostic across biomedical, climate, materials,
# economics, social science. Topic-pack `empirical_triggers` augments this
# core with domain-specific outcome nouns / direction verbs / study subjects
# (see e.g. topic_packs/rapamycin.toml).

_UNIVERSAL_OUTCOME_NOUNS = (
    "effect|gain|reduction|increase|signal|response|benefit|impact|trend|"
    "association|correlation|attenuation|amplification|change|shift|"
    "improvement|deterioration|magnitude"
)
_UNIVERSAL_MAGNITUDE_ADJECTIVES = (
    "substantial(?:ly)?|significant(?:ly)?|consistent(?:ly)?|moderate(?:ly)?|"
    "modest(?:ly)?|robust|null|maximal|larger|smaller|stronger|weaker|greater|"
    "lesser|large|small"
)
_UNIVERSAL_DIRECTION_VERBS = (
    # base[sd]? covers base / base+s (3rd person) / base+d (past simple)
    r"increase[sd]?|decrease[sd]?|reduce[sd]?|elevate[sd]?|raise[sd]?|"
    r"lower(?:s|ed)?|amplif(?:y|ies|ied)|change[sd]?|alter(?:s|ed)?|"
    r"modif(?:y|ies|ied)"
)
_UNIVERSAL_SUBJECTS = (
    "cohorts?|experiments?|trials?|studies|participants?|subjects?|samples?|"
    "datasets?|populations?|observations?|cases?"
)


def _build_empirical_pattern(pack: TopicPack | None) -> re.Pattern[str]:
    """Compose universal core + topic-pack additions into one regex."""
    outcome = _UNIVERSAL_OUTCOME_NOUNS
    direction = _UNIVERSAL_DIRECTION_VERBS
    subjects = _UNIVERSAL_SUBJECTS
    if pack is not None:
        if pack.outcome_nouns_extra:
            outcome = outcome + "|" + "|".join(re.escape(t) for t in pack.outcome_nouns_extra)
        if pack.direction_verbs_extra:
            direction = direction + "|" + "|".join(re.escape(t) for t in pack.direction_verbs_extra)
        if pack.subjects_extra:
            subjects = subjects + "|" + "|".join(re.escape(t) for t in pack.subjects_extra)
    mag = _UNIVERSAL_MAGNITUDE_ADJECTIVES
    parts = [
        r"\b\d+(?:\.\d+)?\s*%",
        r"\bp\s*[<=>]\s*0?\.\d+",
        r"\b(?:hazard|odds|risk|incidence)\s+ratio\b",
        r"\b95\s*%\s*(?:CI|confidence\s+interval)\b",
        r"\beffect\s+size\b",
        r"\bcentral\s+estimate\b",
        r"\bdirectionally\s+concordant\b",
        rf"\b(?:{mag})\s+(?:[\w-]+\s+){{0,3}}(?:{outcome})s?\b",
        rf"\b(?:{outcome})s?\s+(?:is|was|are|were|appears?\s+to\s+be)\s+(?:{mag})\b",
        rf"\b(?:{direction})\s+(?:[\w-]+\s+){{0,3}}(?:{outcome})\b",
        rf"\b(?:{direction})\s+(?:[\w-]+\s+){{0,3}}(?:{outcome})s?\b",
        r"\b(?:was|were|are|is)\s+(?:increased|decreased|reduced|elevated)\b",
        rf"\b(?:{subjects})\s+(?:show(?:s|ed)|demonstrate(?:s|d)|yield(?:s|ed)|"
        r"exhibit(?:s|ed)|reveal(?:s|ed)|display(?:s|ed))\b",
    ]
    return re.compile("|".join(parts), re.IGNORECASE)


# Default universal pattern, used when no pack supplied.
_EMPIRICAL_TRIGGERS = _build_empirical_pattern(None)


_NOVELTY_PHRASES = re.compile(
    r"\b("
    r"no\s+(?:prior\s+)?synthes(?:is|es)\s+has\b|"
    r"no\s+(?:comprehensive\s+|systematic\s+)?(?:review|synthesis|analysis)\s+(?:has|exists)\b|"
    r"first\s+(?:study|meta-?analysis|synthesis)\s+to\b|"
    r"first\s+to\s+(?:evaluate|aggregate|quantify|synthesi[sz]e)\b|"
    r"never\s+(?:been\s+)?(?:evaluated|aggregated|quantified|synthesi[sz]ed)\b|"
    r"never\s+previously\b|"
    r"full\s+breadth\b|"
    r"definitively?\b|"
    r"comprehensive(?:ly)?\s+(?:examined?|aggregated?|evaluated?)\b|"
    r"no\s+comprehensive\s+(?:review|synthesis)\b|"
    r"seminal\s+(?:meta-?analysis|study|synthesis)\b|"
    r"groundbreaking\s+(?:meta-?analysis|study|synthesis)\b|"
    r"pioneering\s+meta-?analysis\b"
    r")\b",
    re.IGNORECASE,
)

# Citation bracket: captures everything between [CIT: and ]. We split the
# inner text on "; CIT:" to handle compound brackets like
# [CIT:foo|role1; CIT:bar|role2] — MiMo emits these despite the prompt.
_CIT_BRACKET = re.compile(r"\[CIT:\s*([^\]]+?)\s*\]")


def _parse_citations(body: str) -> list[tuple[str, str]]:
    """Return [(key, role), ...] for every citation in `body`, splitting compounds."""
    citations: list[tuple[str, str]] = []
    for m in _CIT_BRACKET.finditer(body):
        inner = m.group(1)
        for part in re.split(r"\s*;\s*(?:CIT:)?\s*", inner):
            part = part.strip()
            if not part:
                continue
            key, sep, role = part.partition("|")
            citations.append((key.strip(), role.strip() if sep else ""))
    return citations

_TITLE_MODERATOR_CLAIMS = re.compile(
    r"\b("
    r"(?:but|despite|yet|however)\b[^.]+?\b"
    r"(?:diminish(?:es)?|fail(?:s|ed)?|weaker|stronger|absent|abolished|"
    r"vanish(?:es)?|disappear(?:s|ed)?|attenuat(?:es|ed))\b|"
    r"only\s+(?:in|when|for|among)\b|"
    r"does\s+not\s+(?:extend|prolong|reduce|increase)\b|"
    r"fails\s+to\b|ineffective\b|"
    r"effects?\s+diminish(?:es)?\b|"
    r"effects?\s+abolished\b"
    r")",
    re.IGNORECASE,
)

# Abbreviations whose trailing period must NOT be treated as sentence end.
_ABBREV = re.compile(
    r"\b(?:et\s+al|e\.g|i\.e|cf|Fig|fig|vs|etc|Dr|Drs|Prof|Mrs|Mr|Ms|St|Inc|Ltd|Co|al)\.",
)

# Planned-analysis / methodological framing: sentence is design language, a
# conditional analytical interpretation, or a description of what the analysis
# aims to identify — not a result claim. Skips the soft-trigger check.
_PLANNED_ANALYSIS = re.compile(
    r"\b(?:"
    # Modal + analytical verb ("will quantify", "are designed to identify")
    r"(?:will|would|is\s+planned\s+to|are\s+planned\s+to|"
    r"is\s+specified\s+to|are\s+specified\s+to|"
    r"aims?\s+to|seeks?\s+to|"
    r"is\s+designed\s+to|are\s+designed\s+to)\s+"
    r"(?:quantify|estimate|compute|partition|test|assess|measure|model|evaluate|"
    r"examine|determine|investigate|aggregate|synthesi[sz]e|identify|characteri[sz]e|"
    r"map|address|interrogate|visuali[sz]e|provide|describe|explain|distinguish|"
    r"capture|decompose|disentangle|clarify|adjudicate)"
    # Conditional analytical interpretation ("would indicate", "may suggest")
    r"|(?:would|might|could|may|should)\s+(?:indicate|suggest|imply|reflect|"
    r"signify|reveal|allow|enable|provide|inform|highlight|require|necessitate)"
    # Process verbs that describe what the analysis will perform
    r"|(?:identifying|examining|assessing|testing|exploring|investigating|"
    r"distinguishing|decomposing|partitioning)\s+"
    r"(?:contexts?|conditions?|moderators?|factors?|cases?|patterns?|"
    r"configurations?|sources?|dimensions?)"
    # Explicit pre-specification framing
    r"|pre-?specifie[ds]|pre-?registered|the\s+analysis\s+(?:will|aims|seeks|is)"
    r")",
    re.IGNORECASE,
)

# Question framing: sentence asks a research question rather than asserting a result.
# Skips the soft-trigger check. Quantitative literals still fire regardless.
_QUESTION_INDICATORS = re.compile(
    r"\b(?:"
    r"to\s+what\s+(?:extent|degree)|"
    r"the\s+(?:extent|degree|question)\s+(?:to\s+which|of\s+whether)|"
    r"remain(?:s)?\s+(?:unclear|uncertain|unresolved|incompletely\s+(?:characterized|understood)|"
    r"poorly\s+understood)|"
    r"is\s+(?:currently\s+)?(?:unclear|uncertain|unresolved)|"
    r"are?\s+(?:still\s+)?(?:unclear|uncertain|unresolved|poorly\s+understood)|"
    r"how\s+(?:consistent|robust|much|sensitive|generali[sz]able|reliably|does|do)|"
    r"whether\s+(?:and|or)\s+how"
    r")\b",
    re.IGNORECASE,
)

# Quantitative literals — bare numbers WITHOUT a slot always trigger, even in a
# question or planned-analysis sentence. No exemption.
_QUANTITATIVE_LITERAL = re.compile(
    r"(\b\d+(?:\.\d+)?\s*%|\bp\s*[<=>]\s*0?\.\d+|\b\d+\s*(?:fold|times)\b)",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Sentence split that protects common abbreviations."""
    sentinel = ""
    protected = _ABBREV.sub(lambda m: m.group(0).replace(".", sentinel), text)
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", protected)
    return [s.replace(sentinel, ".").strip() for s in raw if s.strip()]


def gate_evidence_slot(
    sections: dict[str, str], pack: TopicPack | None = None
) -> list[GateViolation]:
    """Police empirical claims for evidence slots.

    Uses universal core triggers plus optional topic-pack extensions
    (`empirical_triggers` in the TOML), so the gate stays domain-agnostic
    while still catching domain-specific terms when a pack is loaded.
    """
    triggers = _build_empirical_pattern(pack) if pack is not None else _EMPIRICAL_TRIGGERS
    violations: list[GateViolation] = []
    for name, body in sections.items():
        if name == "TITLE":
            continue
        for sent in _split_sentences(body):
            if _SLOT_RE.search(sent):
                continue  # claim already anchored
            # Bare quantitative literals always fire — no exemption.
            if _QUANTITATIVE_LITERAL.search(sent):
                _record(violations, name, sent)
                continue
            if not triggers.search(sent):
                continue
            if _PLANNED_ANALYSIS.search(sent) or _QUESTION_INDICATORS.search(sent):
                continue
            _record(violations, name, sent)
    return violations


def _record(violations: list[GateViolation], section: str, sent: str) -> None:
    excerpt = sent if len(sent) <= 140 else sent[:137] + "…"
    violations.append(
        GateViolation(
            gate="evidence_slot",
            location=section,
            message=f"Empirical claim without [CIT:]/[N=]/[EFFECT=] slot: {excerpt!r}",
        )
    )


def gate_novelty_claim(sections: dict[str, str]) -> list[GateViolation]:
    violations: list[GateViolation] = []
    for name, body in sections.items():
        for sent in _split_sentences(body):
            m = _NOVELTY_PHRASES.search(sent)
            if m:
                excerpt = sent if len(sent) <= 140 else sent[:137] + "…"
                violations.append(
                    GateViolation(
                        gate="novelty_claim",
                        location=name,
                        message=f"Forbidden novelty phrase {m.group(0)!r}: {excerpt!r}",
                    )
                )
    return violations


def gate_title_claim(sections: dict[str, str]) -> list[GateViolation]:
    title = sections.get("TITLE", "").strip()
    if not title:
        return []
    m = _TITLE_MODERATOR_CLAIMS.search(title)
    if m:
        return [
            GateViolation(
                gate="title_claim",
                location="TITLE",
                message=(
                    f"Title asserts moderator conclusion ({m.group(0)!r}) before "
                    f"analysis: {title!r}"
                ),
            )
        ]
    return []


def gate_citation_role(
    sections: dict[str, str], pack: TopicPack | None
) -> list[GateViolation]:
    """Every [CIT:] must have a role; role in allowed list; anchors match."""
    if pack is None or not pack.has_cite_roles:
        return []
    violations: list[GateViolation] = []
    allowed = set(pack.cite_roles_allowed)
    for name, body in sections.items():
        for key, role in _parse_citations(body):
            if not role:
                violations.append(
                    GateViolation(
                        gate="citation_role",
                        location=name,
                        message=f"[CIT:{key}] missing |role; expected [CIT:{key}|<role>]",
                    )
                )
                continue
            if role not in allowed:
                violations.append(
                    GateViolation(
                        gate="citation_role",
                        location=name,
                        message=f"[CIT:{key}|{role}] role not in allowed list",
                    )
                )
                continue
            anchor_role = pack.anchors.get(key)
            if anchor_role and role != anchor_role:
                violations.append(
                    GateViolation(
                        gate="citation_role",
                        location=name,
                        message=(
                            f"[CIT:{key}|{role}] anchor expects role "
                            f"{anchor_role!r}, not {role!r}"
                        ),
                    )
                )
    return violations


def gate_scope_consistency(
    sections: dict[str, str], pack: TopicPack | None
) -> list[GateViolation]:
    """Body must not contain topic-pack-discouraged scope terms.

    Citation brackets are stripped before scanning (citation keys may
    legitimately contain words like 'vertebrate' as identifiers).
    """
    if pack is None or not pack.discouraged_terms:
        return []
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(t) for t in pack.discouraged_terms) + r")\b",
        re.IGNORECASE,
    )
    violations: list[GateViolation] = []
    for name, body in sections.items():
        # Strip citation brackets so identifiers inside them don't trigger
        stripped = _CIT_BRACKET.sub("", body)
        for m in pattern.finditer(stripped):
            start = max(0, m.start() - 30)
            end = min(len(stripped), m.end() + 30)
            excerpt = stripped[start:end].replace("\n", " ").strip()
            violations.append(
                GateViolation(
                    gate="scope_consistency",
                    location=name,
                    message=(
                        f"Discouraged scope term {m.group(0)!r}; prefer "
                        f"{list(pack.preferred_terms)}: '…{excerpt}…'"
                    ),
                )
            )
    return violations


def gate_anchor_role_in_prose(
    sections: dict[str, str], pack: TopicPack | None
) -> list[GateViolation]:
    """Prose calling 'X by Surname' must match the anchor role for that surname.

    Catches the 'seminal meta-analysis by Harrison' mistake where Harrison is
    actually a primary-study anchor.
    """
    if pack is None or not pack.anchors:
        return []
    # Build {surname -> role} from anchor keys "surname-year-..."
    by_surname: dict[str, str] = {}
    for key, role in pack.anchors.items():
        parts = key.split("-")
        if parts and parts[0]:
            by_surname.setdefault(parts[0].lower(), role)
    if not by_surname:
        return []
    # Genre nouns that imply a role classification of the cited work
    genre_to_role = {
        "meta-analysis": "prior-meta-analysis",
        "meta analysis": "prior-meta-analysis",
        "meta-analytic": "prior-meta-analysis",
        "systematic review": "systematic-review",
        "narrative review": "narrative-review",
        "mechanism review": "mechanism-review",
        "clinical trial": "clinical-trial",
        "primary study": "primary-study",
    }
    pattern = re.compile(
        r"\b("
        + "|".join(re.escape(g) for g in genre_to_role)
        + r")\s+by\s+([A-Z][a-z]+)",
        re.IGNORECASE,
    )
    violations: list[GateViolation] = []
    for name, body in sections.items():
        for m in pattern.finditer(body):
            genre = m.group(1).lower()
            surname = m.group(2).lower()
            implied_role = genre_to_role[genre]
            anchor_role = by_surname.get(surname)
            if anchor_role and anchor_role != implied_role:
                violations.append(
                    GateViolation(
                        gate="anchor_role_in_prose",
                        location=name,
                        message=(
                            f"Prose calls {m.group(2)} a {genre!r}, but topic pack "
                            f"lists '{surname}-...' as {anchor_role!r}"
                        ),
                    )
                )
    return violations


def gate_length(
    sections: dict[str, str], pack: TopicPack | None
) -> list[GateViolation]:
    """Section word counts must respect topic-pack length_caps."""
    if pack is None or not pack.has_length_caps:
        return []
    violations: list[GateViolation] = []
    for section_key, max_words in pack.length_caps.items():
        body = sections.get(section_key.upper(), "")
        if not body:
            continue
        words = len(re.findall(r"\b\w+\b", body))
        if words > max_words:
            violations.append(
                GateViolation(
                    gate="length",
                    location=section_key.upper(),
                    message=f"{section_key.upper()} is {words} words (cap {max_words})",
                )
            )
    return violations


def gate_citation_density(
    sections: dict[str, str], pack: TopicPack | None
) -> list[GateViolation]:
    """Minimum words per citation bracket — prevents over-citation."""
    if pack is None or pack.min_words_per_citation <= 0:
        return []
    minimum = pack.min_words_per_citation
    violations: list[GateViolation] = []
    for name, body in sections.items():
        if name == "TITLE":
            continue
        words = len(re.findall(r"\b\w+\b", body))
        cites = len(_CIT_BRACKET.findall(body))
        if cites == 0:
            continue
        density = words / cites
        if density < minimum:
            violations.append(
                GateViolation(
                    gate="citation_density",
                    location=name,
                    message=(
                        f"{name} cites every {density:.1f} words ({cites} brackets / "
                        f"{words} words); minimum {minimum} words/bracket"
                    ),
                )
            )
    return violations


def run_all_gates(
    sections: dict[str, str], pack: TopicPack | None = None
) -> list[GateViolation]:
    return (
        gate_evidence_slot(sections, pack)
        + gate_novelty_claim(sections)
        + gate_title_claim(sections)
        + gate_citation_role(sections, pack)
        + gate_scope_consistency(sections, pack)
        + gate_anchor_role_in_prose(sections, pack)
        + gate_length(sections, pack)
        + gate_citation_density(sections, pack)
    )
