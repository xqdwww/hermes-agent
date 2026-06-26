# Travel Series B 44/60 To 50/60 Pipeline Case Study

This file is an example only. Do not treat these scores, case ids, commit hashes, tags, or paths as fixed assumptions for future tasks.

## Historical Sequence

- The project moved from an earlier official baseline to a human-reviewed official 44/60 baseline through controlled evidence, no-write candidate rerun, human review, separate baseline write, and separate runtime metadata alignment.
- A later six-case source-gap batch passed Hermes acquisition, Codex intake/formal-ready/handoff, sequential controlled execution, archive, and 23-case controlled evidence rollup.
- That produced a 50/60 candidate-only result, not an official score. Human review then determined whether those six candidate deltas could proceed to a separate baseline write task.

## Useful Patterns

- `cross_route_053` illustrated source gap -> intake -> controlled execution -> candidate -> human review -> baseline write, with caveats for context evidence and rejected sources.
- The next batch illustrated source acquisition -> Codex intake/formal-ready/handoff -> sequential controlled execution -> candidate-only score movement.
- Runtime metadata once failed closed on stale expected score, demonstrating that runtime alignment must happen after baseline commit and must be separately tested.
- A source-gap acquisition skill was created as a lower-level subskill for material acquisition.
- Disk-space guard mattered before bundle generation and intake/vectorization.
- External fork push was not assumed; local bundle fallback was used when the approval layer blocked external disclosure.

## Lessons

Candidate-only score is not official. Controlled evidence is not official. Source acquisition is not controlled evidence. Human review does not write baseline. Baseline write does not update runtime metadata unless separately authorized. Runtime smoke and backup close the release.
