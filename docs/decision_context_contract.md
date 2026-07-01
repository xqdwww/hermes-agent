# Decision Context Contract

This document describes Phase 1 of the decision context contract work.

Phase 1 adds a deterministic, offline schema and generator in
`tools/decision_context_contract.py`. It does not change convergence,
external calibration, final controller rendering, final validation gates,
Stage A execution, Stage B execution, hard-gate routing, or the live wrapper.

## Purpose

The contract preserves user-facing decision requirements before later phases
wire them into Decision stages. It captures:

- task topic and topic drift guards
- source provenance for the original query, Stage A packet, and L2.5 outputs
- required output sections
- required per-item fields
- key variables
- moderator variables
- required dimensions
- evidence tiers
- forbidden content
- forbidden internal terms
- claim strength policy
- final acceptance checks

## Phase 1 Boundary

The generator is deterministic and offline. It reads only the supplied original
query, the supplied research packet path, and optional or inferred L2.5
`sources.csv`, `evidence.csv`, `claims.md`, and `gaps.md` files. It does not
call external services, does not write production artifacts, and is not imported
by the runner.

Later phases can decide how to pass the contract into convergence, calibration,
final rendering, and final validation. Until then, Phase 1 is schema and test
coverage only.
