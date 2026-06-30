# External Pattern Review Template

## Scope

- task:
- reviewer:
- date:
- repo:
- branch:
- head:
- approved_files:
- blocked_actions:

## Target Skill

- skill_name:
- skill_path:
- skill_family:
- requested_change:

## Trigger Reason

- scope_classification:
- review_required: yes/no
- rationale:
- user_confirmation_needed:

## Sources Reviewed

| source | source_class | why relevant | access mode | security risk | notes |
| --- | --- | --- | --- | --- | --- |
|  | mature skill / official docs / repo-example / paper-standard / best-practice |  | read-only |  |  |

## Pattern Extraction

| source | pattern extracted | why it works | local adaptation | confidence |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Anti-Pattern Review

| anti-pattern | source or observation | why rejected | local guardrail |
| --- | --- | --- | --- |
| blind copy-paste |  |  |  |
| clone/install/run unknown code |  |  |  |
| popularity as quality proof |  |  |  |
| missing tests/contract before implementation |  |  |  |

## Security Review

- external repositories read-only:
- no clone/install/run unknown code:
- license or attribution concerns:
- prompt-injection or instruction-smuggling concerns:
- dependency risks:
- sandboxing required:
- user authorization required:

## Local Adaptation Plan

- local purpose:
- trigger conditions:
- when not to use:
- input contract:
- output contract:
- required artifacts:
- failure modes:
- stop rules:
- user confirmation boundaries:
- test strategy:
- files allowed to change:
- files explicitly out of scope:

## Implementation Gate Decision

- pattern_review_complete: yes/no
- local_contract_complete: yes/no
- tests_plan_complete: yes/no
- security_review_complete: yes/no
- implementation_gate_status:
- blocked_reason:

## Tests Plan

- positive tests:
- negative tests:
- dry-run scenarios:
- security-boundary tests:
- markdown/frontmatter tests:
- scope tests:
- commands to run:

## Final Recommendation

- status:
- implementation_allowed: yes/no
- required_next_step:
- remaining_risks:
- handoff_owner:
