# Approved Source Manifest Schema

This document describes the portable `approved-source-manifest.v1` shape used by the Series B source-gap controlled regression workflow.

The schema is case-scoped only. It is not a production-default manifest format, and it does not authorize production builder loading.

## Required Top-Level Fields

An `approved-source-manifest.v1` object must include exactly the expected top-level contract fields for controlled use:

- `manifest_version`
- `manifest_id`
- `case_id`
- `case_scope_only`
- `production_default`
- `created_at`
- `created_by`
- `approved_status`
- `approval_scope`
- `target_gap`
- `target_term`
- `source_policy`
- `allowed_axes`
- `forbidden_axes`
- `sources`
- `eval_binding`
- `safety_gates`
- `notes`

Required values:

- `manifest_version` must be `approved-source-manifest.v1`.
- `case_scope_only` must be `true`.
- `production_default` must be `false`.
- `allowed_axes` must be non-empty.
- `forbidden_axes` must include rejected source categories such as `food_book`, `open_evidence`, `wiki`, `zim`, `generic_web`, `unknown_source`, and `unconfirmed_source`.

## Required Per-Source Fields

Each source entry must include:

- `source_id`
- `source_title`
- `source_author_or_editor`
- `source_publisher`
- `source_year`
- `source_type`
- `source_axis`
- `allowed_axis`
- `professional_axis_eligible`
- `source_role`
- `source_path_or_locator`
- `source_sha256`
- `provenance_status`
- `provenance_evidence`
- `accepted_chunk_ids`
- `supporting_chunk_ids`
- `case_relevance_reason`
- `approved_for_case_id`
- `not_valid_for_other_cases`
- `forbidden_as_open_evidence_upgrade`

Required source values:

- `source_sha256` must be present.
- `provenance_status` must be `confirmed`.
- `professional_axis_eligible` must be `true`.
- `approved_for_case_id` must exactly match the manifest `case_id`.
- `not_valid_for_other_cases` must be `true`.
- `forbidden_as_open_evidence_upgrade` must be `true`.
- `accepted_chunk_ids` must be non-empty.

## Source Policy

The controlled manifest must fail closed if it permits:

- cross-case reuse;
- open-evidence professional-axis upgrade;
- Wiki/ZIM professional-axis upgrade;
- food-book noise as an accepted axis;
- implicit fallback beyond the declared case scope.

Open evidence, Wiki, and ZIM material may help with discovery or disambiguation, but they must not satisfy a professional source axis.

## Eval Binding

`eval_binding` must restrict the manifest to controlled touched-eval use:

- `expected_case_id` must exactly match `case_id`.
- `controlled_only` must be `true`.
- `touched_eval_only` must be `true`.
- mutation of production builder, dataset, source tables, scoring, audit, gate, or cap must remain forbidden.

## Fail-Closed Rules

The loader or reviewer must reject the manifest if any of the following occurs:

- invalid JSON;
- missing required field;
- unexpected field in the strict manifest contract;
- `case_id` mismatch;
- `case_scope_only` missing or false;
- `production_default` missing or true;
- missing or mismatched source SHA-256;
- provenance status not confirmed;
- source axis outside `allowed_axes`;
- source axis in `forbidden_axes`;
- `food_book`, `open_evidence`, `wiki`, `zim`, `generic_web`, `unknown_source`, or `unconfirmed_source` used as a professional axis;
- source approved for a different case;
- cross-case generalization;
- any fallback to source-title or term fuzzy matching after manifest validation fails.

## Production Boundary

This schema is a controlled-regression artifact. It does not define production ingestion, production retrieval, or production builder behavior.

Future production use requires separate review and explicit authorization.
