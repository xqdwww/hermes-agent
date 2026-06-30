# Full-Text Source Integration Contract

This helper validates deterministic handoff manifests between Stage A source registry artifacts and Stage B Evidence Packet v2 generation.

It does not search, retrieve full text, call an LLM, verify claims, synthesize finals, or integrate with production pipeline runtime.

## Required Handoff Item Fields

- source_id
- case_id
- registry_path
- url_or_local_ref
- retrieval_status
- full_text_available
- full_text_accessed
- excerpt_ref_id
- excerpt_or_span
- excerpt_summary
- section_locator
- access_date
- source_hash_or_locator
- allowed_claim_categories
- prohibited_claim_categories
- full_text_verified_allowed
- high_risk_allowed
- caveats
- handoff_ready

## Gate Semantics

- full_text_verified_allowed false prevents Stage B from marking claims as full_text_verified from that source.
- high_risk_allowed false prevents high-risk support upgrades from that source.
- handoff_ready false blocks Stage B support upgrades but may still allow cautious/source_need citation.
