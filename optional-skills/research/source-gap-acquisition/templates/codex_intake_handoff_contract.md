# Codex Intake Handoff Contract

Use this contract after Hermes source acquisition has produced reports and raw/context files.

## Inputs

- Hermes source acquisition report(s)
- usable source validation manifest(s)
- rejected source validation manifest(s)
- downloaded/found file manifest
- raw/context directories for selected cases
- original case prompt / gap extraction report
- policy report for adversarial or malformed-token cases

## Codex Stage Boundary

Codex may perform local intake only when explicitly authorized:

- validate source-backed bodies
- normalize source text
- create page maps or section locators
- chunk source text
- sandbox-vectorize candidate chunks only if authorized
- run readiness review
- run formal-ready review
- generate controlled handoff if approved

## Prohibited In This Stage

- no controlled execution
- no official candidate rerun
- no baseline update
- no production mutation
- no production vector index write
- no source raw deletion or movement
- no use of rejected sources as evidence

## Stop Conditions

Stop if:

- source validation is invalid or missing
- exact case prompt cannot be recovered
- required terms/axes/sections are not source-backed
- source is Cloudflare/interstitial, README, generated summary, title-only, listing/booking/ticket contamination, or wrong context
- policy-gated case lacks a policy decision

## Output

Produce readiness/formal-ready/handoff reports only. Treat all outputs as pre-controlled evidence until a separate controlled execution task passes.
