# Runtime Metadata Update Prompt

Use only after an official baseline write commit exists.

Rules:

- Confirm baseline commit and tag/status if relevant.
- Update production/runtime metadata expected score and caveats only.
- Do not modify official baseline current/ledger.
- Run non-destructive sanity and runtime smoke.
- Commit runtime metadata separately.
- Do not write production vector index.
- Stop on smoke failure or scope drift.
