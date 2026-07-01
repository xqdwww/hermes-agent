# Decision Context Contract

This document describes the decision context contract work.

Phase 1 added a deterministic, offline schema and generator in
`tools/decision_context_contract.py`.

Phase 2 wires that contract into production DECISION convergence and external
calibration. It still does not change final controller rendering, final
validation gates, Stage A execution, hard-gate routing, Travel skills, or
Academic skills.

Phase 3 makes the DECISION final controller render from the validated contract
plus validated convergence and calibration inputs. It still does not change
Stage A, L2.5, convergence/calibration execution, final validation gates,
hard-gate routing, Travel skills, or Academic skills.

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
call external services and does not write production artifacts by itself.

## Phase 2 Boundary

Production DECISION full generates:

- `decision_context_contract/decision_context_contract.json`
- `decision_context_contract/decision_context_contract.md`

Convergence receives the contract as hard input context and is validated with
deterministic checks for:

- contract ID and task topic presence
- key variable retention
- moderator retention
- required dimension coverage
- evidence tier presence
- meta execution/readiness drift

External calibration receives the same contract plus convergence and is
validated against the same user decision object. Calibration that instead
calibrates pipeline execution, schema readiness, production rollout, pilot
readiness, task-engine implementation, or tool availability must fail closed.

Phase 2 intentionally does not render a new final answer and does not modify the
final controller or final validation gates.

## Phase 3 Boundary

Production DECISION final controller now reads:

- `decision_context_contract/decision_context_contract.json`
- validated `convergence_report.md`
- validated `external_calibration.md`
- the original query and contract task topic

When a contract is required but missing or invalid, final controller fails
closed with `FINAL_CONTROLLER_MISSING_DECISION_CONTEXT_CONTRACT`.

The renderer inherits the contract fields directly:

- required sections
- required TopN counts
- required item fields
- key variables
- moderator variables
- required dimensions
- evidence tiers
- forbidden internal terms

For Top5 outputs, each item must explicitly render the contract fields instead
of relying on paragraph-only implicit coverage. This phase does not add a new
global final validation gate; it enforces the contract inside final controller
rendering before the existing quality checks run.
