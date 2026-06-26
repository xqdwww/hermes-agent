# Release Backup And Smoke Prompt

Use for post-write or post-runtime closure.

Rules:

- Run disk-space guard.
- Run non-destructive sanity and runtime smoke.
- Create local git bundle with branch and relevant local tags.
- Verify bundle and optionally clone-verify repo-outside.
- Follow remote policy: fork only if authorized, never origin, never force, never push all tags.
- Stop on runtime smoke failure, bundle failure, non-fast-forward remote, or tag mismatch.
- Use local-only fallback if external push is blocked.
