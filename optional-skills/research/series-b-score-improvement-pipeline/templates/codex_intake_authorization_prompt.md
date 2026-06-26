# Codex Intake Authorization Prompt

Use this prompt after Hermes source acquisition outputs exist.

Requirements:

- Consume Hermes source-acquisition reports and raw/context dirs only.
- Audit all inputs against `source-gap-acquisition`.
- Run disk-space guard before intake/vectorization.
- Perform local intake, normalization, page maps, chunking, and sandbox vectorization only for authorized case dirs.
- Run readiness, formal-ready review, and handoff only.
- Do not run controlled execution.
- Do not update official baseline.
- Do not modify production/runtime metadata.
- Do not mutate source raw.
- Do not commit by default.
- Stop on invalid source, policy gap, dirty scope, or low disk.

Final output must list cases valid for intake, cases approved for handoff, partial/blocked cases, caveats, reports written, and next controlled-execution queue.
