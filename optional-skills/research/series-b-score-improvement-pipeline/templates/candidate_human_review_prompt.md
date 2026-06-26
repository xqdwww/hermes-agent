# Candidate Human Review Prompt

Review a no-write candidate result.

Rules:

- Treat candidate score as candidate-only.
- Compare candidate against current official baseline.
- Identify newly countable cases and unchanged cases.
- For each delta case, audit evidence body, caveats, rejected-source exclusion, source-axis overclaim, contamination, controlled artifacts, and archive completeness.
- Decide approved, approved with caveat, needs more evidence, or rejected.
- Produce baseline readiness verdict.
- Do not write official baseline.
- Do not run another candidate rerun.
