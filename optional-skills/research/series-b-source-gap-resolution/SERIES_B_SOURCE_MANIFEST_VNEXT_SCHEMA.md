# Series B Source Manifest vNext Schema

This document defines the draft `series_b_source_manifest.vNext.draft`
contract for the Series B travel background dossier source-gap workflow.

The vNext schema is a case-scoped controlled-regression artifact. It is
not a production-default manifest format, does not run Series B, and does
not authorize official baseline updates.

## Status

- Schema version: `series_b_source_manifest.vNext.draft`
- Scope: case-scoped controlled regression and schema validation only
- Production default loader: disabled
- Full Series B auto-use: disabled
- Official baseline update: disabled
- Case repair: out of scope for this schema document

The official Series B baseline remains frozen around `31/60`. Local Run A
`1/60`, local Run B `4/60`, and any prototype evidence remain guarded
dry-run evidence only.

## Why vNext Exists

The existing `approved-source-manifest.v1` contract is intentionally
strict and professional-source oriented. It protects the three controlled
reference cases, but it does not provide separate buckets for context
evidence, prototype evidence, excluded sources, and machine-readable axis
satisfaction.

vNext keeps the old production boundary intact while making evidence
roles explicit:

- `professional_sources`: sources eligible to satisfy professional axes.
- `context_sources`: Wiki/ZIM, encyclopedia, glossary, or extracted
  context packets used only for disambiguation, background, or context
  axes.
- `prototype_evidence`: exploratory artifacts that must not count as a
  formal controlled pass.
- `excluded_sources`: title-only, query echo, generated echo,
  wrong-context, listing, or other rejected evidence.
- `axis_satisfaction`: explicit mapping from each required axis to the
  source ids that satisfy it.
- `formal_pass_gate`: a machine-readable gate summary.
- `production_path_policy`: explicit production and baseline locks.

## Required Top-Level Fields

A `series_b_source_manifest.vNext.draft` object must include:

- `schema_version`
- `case_id`
- `case_family`
- `required_professional_axes`
- `required_context_axes`
- `professional_sources`
- `context_sources`
- `prototype_evidence`
- `excluded_sources`
- `axis_satisfaction`
- `formal_pass_gate`
- `production_path_policy`

Unexpected top-level fields should fail closed in the standalone validator.

## Professional Sources

Each `professional_sources[]` entry must include:

- `source_id`
- `axis`
- `source_group`
- `title`
- `source_path` or `source_path_or_locator`
- `source_sha256` or `identity_hash`
- `license_or_provenance_status`
- `ingestion_run_id`
- `accepted_chunks`
- `supports_terms`
- `supports_sections`
- `wrong_context_guard`
- `formal_ready`

The professional `axis` must be one of:

- `religion_book`
- `history_book`
- `materials_book`
- `archaeology_book`
- `nature_book`
- `geography_book`
- `art_architecture_book`
- `food_book`
- `architecture_book`
- `engineering_book`
- `conservation_book`
- `local_history_book`

Rules:

- `accepted_chunks` must be non-empty.
- A formal-ready source must have confirmed or approved provenance.
- A formal-ready source must have a stable locator and identity hash.
- Title-only, query echo, generated echo, image filename, weak inventory,
  wrong-context, and listing/travel-planning records must not appear in
  `professional_sources`.

## Context Sources

Each `context_sources[]` entry must include:

- `source_id`
- `axis`
- `role: context_only`
- `supports_disambiguation`
- `supports_terms`
- `supports_sections`
- `cannot_satisfy_professional_axis: true`

Context axes include:

- `wiki_or_zim`
- `encyclopedia`
- `gazetteer`
- `local_guide_context`
- `source_backed_extracted_context_packet`
- `domain_glossary`

Wiki/ZIM can be a context source and can satisfy `wiki_or_zim`. It must
not satisfy `materials_book`, `archaeology_book`, `religion_book`,
`history_book`, `nature_book`, `art_architecture_book`, or any other
professional source axis.

## Prototype Evidence

Each `prototype_evidence[]` entry must include:

- `artifact`
- `status: prototype_only`
- `cannot_be_counted_as_formal_pass: true`
- `cannot_update_official_baseline: true`

Prototype evidence is useful for audit trails and future planning, but it
must not satisfy formal axes or official baseline gates.

## Excluded Sources

Each `excluded_sources[]` entry must include:

- `source_id`
- `reason`
- `excluded_from_axes`
- `notes`

Allowed exclusion reasons:

- `title_only`
- `query_echo`
- `generated_echo`
- `image_filename_only`
- `wrong_context`
- `listing_or_travel_planning`
- `modern_event_irrelevant`
- `food_only_wrong_case`
- `generic_orientation_or_platform`
- `weak_inventory_only`

Any source listed in `excluded_sources` must not be used by
`axis_satisfaction`.

## Axis Satisfaction

Each required axis must appear once in `axis_satisfaction[]`.

For a professional axis:

- `axis_type` must be `professional`.
- `satisfied_by_category` must be `professional_sources` when satisfied.
- Every `satisfied_by_source_ids[]` item must refer to a formal-ready
  professional source with the same axis.

For a context axis:

- `axis_type` must be `context`.
- `satisfied_by_category` may be `context_sources`.
- Context satisfaction must not spill into professional axes.

## Formal Pass Gate

`formal_pass_gate` must include:

- `required_professional_axes_satisfied`
- `context_sources_used_as_professional_sources`
- `prototype_evidence_used_as_formal_pass`
- `decision`
- `blocked_reasons`

Allowed decisions:

- `FORMAL_PASS_READY`
- `SOURCE_AXIS_BLOCKED`
- `EXTERNAL_PROTOTYPE_ONLY`
- `LONG_DEFER_SOURCE_NEEDED`
- `BLOCKED_PROFESSIONAL_SOURCE_UNAVAILABLE`
- `FAIL_CLOSED`

`FORMAL_PASS_READY` is valid only when every required professional axis is
satisfied by `professional_sources`, no context source is used as a
professional source, and no prototype evidence is used as formal pass
evidence.

## Production Path Policy

`production_path_policy` must include:

- `case_scoped_only: true`
- `production_default_loader_enabled: false`
- `full_series_b_enabled: false`
- `official_baseline_update_enabled: false`

The standalone validator must reject any manifest that sets production
default loading, full Series B use, or official baseline update to `true`.

## Compatibility With the Three Existing Controlled Cases

The existing controlled evidence for:

- `nat_eco_039`
- `obj_art_010`
- `hist_arch_024`

keeps its original meaning. This patch does not upgrade those cases to an
official baseline, does not require immediate migration, does not change
their pass/fail history, and does not automatically connect vNext to the
old controlled wrapper or production default behavior.

An optional future migration adapter may translate old controlled
reference metadata into non-executable vNext draft manifests, but that is
outside this minimal patch.

## Standalone Validator

Use the validator only as an explicit local tool:

```bash
python3 optional-skills/research/series-b-source-gap-resolution/validate_series_b_source_manifest_vnext.py \
  optional-skills/research/series-b-source-gap-resolution/series_b_source_manifest_vnext_example.json
```

Run the built-in smoke checks:

```bash
python3 optional-skills/research/series-b-source-gap-resolution/validate_series_b_source_manifest_vnext.py --self-test
```

The validator is standalone. It is not imported by production builder
code, does not run Series B, and does not update any baseline artifact.
