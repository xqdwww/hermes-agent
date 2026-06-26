# Baseline Write Authorization Prompt

Use only after candidate human review explicitly approves a recommended official score.

Rules:

- Confirm repo branch/head and clean status.
- Modify only official baseline current/ledger unless separately authorized.
- Preserve caveats and remaining failed/deferred cases.
- Validate JSON and scope.
- Commit baseline files only.
- Do not modify production/runtime metadata in the same task unless separately authorized.
- Do not push or tag unless explicitly authorized.
