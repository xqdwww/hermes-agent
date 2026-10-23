# OpenClash/AntiGravity incident lessons (2.7.10)

Read this reference before node audit or recovery, AntiGravity integration,
activation, or debugging a service that passes health checks but fails real
generation. It records the 2026-10-12 operational lessons. A route label,
HTTP response, or saved candidate is evidence about that observation only; it
is not proof of a different service, account, or current route.

## Invariants

1. **Preserve the control path and attribution.** Keep the working GPT control
   path intact while investigating Gemini. Record the selected group, selected
   node, default, proxy mode, and route marker before any change. Desktop Clash
   Verge and router OpenClash are separate paths: a generation through desktop
   Clash Verge while OpenClash is disabled proves the desktop path, not the
   router's selected node. Preserve the desktop configuration and disabled
   router state when that is the user's working recovery path.

2. **Keep incremental reuse exact and evidence-bound.** Under the user's
   ordinary-update policy, a same exact-name node receives its new parameters
   without service retesting. Only added or renamed names are tested ordinarily;
   `--full-retest` is explicit. Parameter replacement must not rewrite
   identity-bound proof or its timestamp. Keep a current failure as a new
   record without erasing historical proof. Ordinary updates may keep using
   exact-name carried policy without retesting; after an observed live failure,
   however, recovery must leave the current route on a fresh live pass.

   Candidate membership and identity-bound proof are separate records. The
   current production candidate group is the authoritative name-based seed for
   an ordinary same-name update. A changed connection identity may stop an old
   registry proof from matching, but it must never subtract that same name from
   the carried candidate group. Reconcile a repaired pool as: current accepted
   candidate names plus current exact-identity actual-use passes, minus removed
   names and exact current-snapshot definitive service region failures. An
   unexplained pool-count collapse is a regression to investigate, not proof
   that the missing nodes became unusable.

3. **Use service-specific actual-use proof.** GPT candidate admission requires
   a real GPT generation on the exact current desktop route; HTTP health,
   RegionRestrictionCheck, login redirects, or another OpenAI surface do not
   prove the required GPT path. Gemini candidate admission requires real
   CloudCode generation and an end-to-end authenticated AntiGravity request;
   `generate_204`, `/health`, HTTP 200, reachability, and region screening are
   transport or screening evidence only. CloudCode proof does not prove Gemini
   Web or AI Studio eligibility. Keep GPT Hong Kong-labelled nodes out of both
   the GPT candidate pool and GPT manual group, including on recovery paths.

   For AntiGravity, do not hard-code a historical CloudCode model alias in the
   probe. Model aliases can disappear while the account still has quota, and
   CloudCode can then return `RESOURCE_EXHAUSTED` for every route. Calibrate one
   known-good node first through the installed `agy`/AntiGravity client with a
   model currently advertised by that client, require a unique generated marker
   and a CloudCode connection-chain match, then run the bounded node batch. If
   calibration fails globally, classify the run as account/model-path failure
   and do not alter candidate membership. Authentication, transport, timeout,
   and rate-limit outcomes are inconclusive; only a route-confirmed explicit
   region/location rejection may remove a Gemini candidate.

4. **Route the right CloudCode endpoints.** Production, daily, and
   daily-sandbox CloudCode endpoints are distinct paths. Route and validate
   each exact configured CloudCode domain; success on one endpoint does not
   establish the others. OpenClash should use narrow exact-domain CloudCode
   rules rather than a broad `googleapis.com` capture. Keep a manual group as a
   direct-node recovery choice with an explicit candidate option; a curated
   candidate `fallback` is the evidence-backed automatic pool. A manual group
   must not promote every reachable or historically seen node into the curated
   pool. Apply manual exclusions per service: GPT always excludes Hong Kong
   labels, while Gemini excludes only definitive Gemini-specific blocks.

5. **Use the proven AntiGravity architecture.** AntiGravity should use
   system-default networking with its internal upstream and native proxy pool
   disabled; OpenClash narrowly routes the CloudCode domains through
   `Gemini专用`. An authenticated native proxy pool or upstream can appear
   configured while its runtime binding and OAuth/model path fail. HTTP or SOCKS
   reachability of that pool does not prove that AntiGravity's internal OAuth
   flow uses it. Native pool/upstream modes require an independent OAuth and
   model-path proof before they may be selected.

6. **Test selectors serially and recover the first live pass.** For each node,
   switch the selector, read it back by exact full name, reset the connection,
   allow stabilization, and then run the service-specific test. Do not run
   selector changes in parallel. Stop on the first live pass and keep it as the
   recovery route. If no candidate passes, restore the last known-good
   selector/default, verify that route, and record every failed current attempt.
   After any restart, verify that selector state and defaults persisted before
   accepting traffic. If persistent selector storage is not guaranteed, place
   the verified recovery node first in the generated manual group. In-memory
   state is not restart-safe evidence.

7. **Handle OAuth and secrets without round-tripping them.** Secure UI password
   fields may be masked and read as empty. Never write an empty read-back value
   over an existing secret. When extracting an OAuth client secret from a
   binary, match the fixed Google desktop-secret form
   `GOCSPX-[A-Za-z0-9_-]{28}`; `strings` output can concatenate adjacent
   constants and is not a safe delimiter. Send a refresh token only to Google's
   OAuth token endpoint, and capture only a masked or hashed identifier.

8. **Back up atomically and preserve rollback.** Before token/config changes
   or an app upgrade, make atomic mode-0600 backups of token/config files and a
   separate reversible backup of the app bundle, preserving identity-bound
   state and selector defaults. Use official app artifacts and verify the
   intended version. Compare signing diagnostics with the old build before
   blaming a warning on the upgrade, and never assume a version upgrade fixed
   proxy behavior without retesting OAuth and model traffic. An upgrade is
   accepted only after end-to-end validation;
   restore the backup and stop if state, OAuth, or model-path behavior regresses.
   Never report secrets, tokens, email addresses, router passwords, private
   payloads, or raw OAuth material. Evidence and reports must be secret-free
   and mode 0600.

## Decision and recovery sequence

1. Snapshot the GPT control path, desktop/router attribution, selectors,
   defaults, and atomic backups. If the working path cannot be identified,
   stop before changing a node or app.
2. Confirm the exact production, daily, and daily-sandbox CloudCode domains
   and the system-default-via-OpenClash architecture. Disable internal
   upstream/pool modes unless their independent OAuth and model-path proof is
   already present.
3. Test selectors one at a time. Restore and verify the first live pass after
   any failed test or restart. Do not promote a node from health or screening
   evidence alone.
4. For Gemini, require real CloudCode generation and a complete AntiGravity
   request. For final acceptance, require AntiGravity's `/health`,
   `/v1/models`, and a marker-based `/v1/chat/completions` response, then
   confirm the end-to-end request on the intended current route. For GPT,
   require the corresponding real GPT generation on the current desktop route.
5. If any proof fails, record the current failure with its exact node identity,
   route, endpoint, and timestamp; preserve identity-bound historical proof but
   leave the current selection on a fresh live pass. Restore the last known-good
   selector/default or app backup and stop activation when restoration or final
   acceptance fails.
