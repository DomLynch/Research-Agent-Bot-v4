# v4 Alpha-Memo — Task & Feedback Tracker

Single source of truth for open work, reviewer feedback, and the publish-rate
diagnosis. Newest first. Status: ☐ open · ◐ in progress · ☑ done · ⏸ parked.

---

## P0 — ACTIVE: zero-publish outage (diagnosed 2026-05-31)

**Symptom:** 0 memos published for ~2 days. Every cron cycle ends
`no_publishable_candidate`, `submitted=0 published=0`.

**Root cause (NOT a code regression — verified on VPS):** seed-pool exhaustion
colliding with cooldown + thin topics.
- The 6 proven winners (acarbose, caloric_restriction, exercise, metformin,
  rapamycin, telomere) each meet the 5/5 source floor but are all inside the
  **30-day published-topic cooldown** → `cycle_exhausted_topic`.
- GLP_1_longevity meets the floor (7 src / 5 direct) but is blocked
  `duplicate_submission_fingerprint` (submitted before, reviewer wanted rescope).
- Every remaining seed is genuinely thin after dedupe (berberine 2, quercetin 4,
  dasatinib 2, klotho 2, omega_3 4/2, vitamin_D 3/2, gait_speed 3/2,
  plasma_exchange 5/3) → below floor.
- `discovery_seeds.toml` has only 26 topics; refresh ran `ran_topics=0`,
  `note="all_candidate_topics_excluded_or_in_cooldown"`. **No fresh topics exist
  to build**, so the bot has nowhere to go.
- The thin-topic runs are STALE (built before P4/P5/P7 deployed), so the lane
  reclassification has never been applied to them.

**Fix plan (stop the bleeding):**
1. ☐ **Expand `discovery_seeds.toml`** (+30-50 fresh longevity/medical topics
   never published). Data-only, zero code, universal. Gives refresh new topics.
   HIGHEST leverage / lowest risk.
2. ☐ **Rebuild the thin topics fresh** (runtime) so P4/P5/P7 apply — tests
   whether berberine/quercetin/klotho lift above floor once D_bad facts
   reclassify to B_context. This is the live proof P4 works.
3. ☐ **Close the GLP-1 duplicate loop** — it should rescope+resubmit (grounded
   mode already exists); confirm why it's still hard-blocked vs repairable.
4. ⏸ Do NOT lower the 30-day cooldown (would churn same topics → Researka
   duplicate rejects). Prefer fresh topics over republishing.

---

## Open follow-ups (carried, not yet done)

- ☐ **DB-side PICO completeness** — topics like quercetin had 43/58 facts in
  D_bad for empty population/intervention columns. P4 mitigates v4-side; the
  root is incomplete DB extraction. Owner: DB dev.
- ☐ **P4 live verification** — lane reclassification proven by unit tests only;
  needs a real cron cycle rebuilding berberine/quercetin/klotho to confirm the
  publish-rate lift. (Blocked on task P0-2 above.)

## Parked — need explicit go-ahead (external dependency)

- ⏸ **RoBBR risk-of-bias** in `memo_audit.json` (currently `not_assessed`).
  Needs an LLM route; model stack is LOCKED to MiMo + Gemma — requires approval.
- ⏸ **OpenScholar nearest-literature delta** in `memo_audit.json` (currently
  `null`). Needs the 45M-paper datastore — not present, heavy infra.

## Test-coverage backlog (from session handoff, p70)

- ☐ cover `extract_all_anchors` / `find_closest_anchor` [agent/source_corpus.py]
- ☐ cover `load_alpha_boosts` [agent/alpha_selector.py]
- ☐ cover `validate_outcomes` / `validate_effects` [agent/effect_sizes.py]

---

## Done (recent, newest first)

- ☑ P5 source-key hardening completed across all 4 files incl. publish_tier
  (`4888fd4`, operator-approved gatekeeper edit, identity-ordering only).
- ☑ P1-P7 supply-chain plan: lane reclassification (D_bad only when BOTH PICO
  empty), refresh_top 1→5, source-key hardening, synonyms (`d50ba75`/`2e64156`).
- ☑ FactReview-style `memo_audit.json` audit pack (`01caeba`).
- ☑ OpenSeeker `search_trace.json` + paper-qa `journal_quality` (`2c66e90`).
- ☑ V4 borrows: novelty archive, claim-receipt matrix, falsifier gate, golden
  eval (`d82c91e`).
- ☑ Grounded-rescope for scope-reset rejects; publish_queue gitignored.
