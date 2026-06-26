# Controlled Execution Queue Prompt

Run a sequential case-scoped controlled execution queue.

Rules:

- Process one case at a time in the user-specified order.
- Validate handoff inputs before patching.
- Patch only case-scoped tools/tests or safe shared helpers.
- Run vNext/self tests, current case tests, runner help, diff check, and pycache/pyc guard.
- Commit exactly one guarded case if tests pass.
- Run post-commit guard.
- Execute one single-case controlled dry-run.
- Archive only if result is `PASS_CONTROLLED_REGRESSION`.
- Stop on first fail, partial, blocked, test failure, or dirty scope.
- Write rollup only if all selected cases pass.
- Do not update official baseline.
