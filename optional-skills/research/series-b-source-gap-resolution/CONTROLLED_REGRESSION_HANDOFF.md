# Controlled Regression Handoff

This document records the sanitized handoff for the Series B source-gap controlled regression assets associated with the hidden draft optional skill `series-b-source-gap-resolution`.

## Status

- Controlled regression artifact only.
- Case-scoped only.
- Production default remains unchanged.
- Official Series B baseline remains frozen at `31/60`.
- Not a production pass.
- Not a full Series B improvement claim.
- Raw controlled-run outputs remain outside the repository in Codex task outputs.
- Future production use requires separate review and explicit authorization.

## Controlled Cases

The following approved controlled cases passed in a case-scoped harness:

| Case ID | Target | Approved Sources | Controlled Status |
|---|---|---|---|
| `nat_eco_039` | `overdeepening` | `Glaciers and Glaciation` | `PASS` |
| `obj_art_010` | `kento/kentō` | `Japanese Woodblock Prints`; `Edo Culture: Daily Life and Diversions in Urban Japan, 1600-1868` | `PASS` |
| `hist_arch_024` | `fauces` | `Herculaneum: Past and Future` | `PASS` |

The `obj_art_010` target includes both the plain romanized form `kento` and the macron spelling `kentō`.

## What This Means

The controlled harness confirmed that the approved case-scoped manifests can resolve the targeted source/term/axis gaps for the three named cases when invoked explicitly in the controlled workflow.

The result is useful as a regression reference for future review. It does not change the production builder, default retrieval behavior, source tables, scoring, audit, gate, cap, dataset, OCR, embeddings, or official Series B score.

## What Stays Out Of Repo

The following remain as local/Codex audit artifacts and should not be committed as-is:

- raw smoke result JSON;
- generated wrapper reports;
- generated ledger reports;
- generated freeze inventories;
- local harness scripts;
- raw fixtures that include local filesystem paths;
- any output under `outputs/`.

## Future Review Boundary

Production use remains a separate decision. A future production design would need to review manifest loading, source authority behavior, source table policy, regression coverage, public hygiene guardrails, rollback behavior, and whether approved sources may enter production-default selection.

Until that review is complete, these assets are documentation and controlled-regression references only.
