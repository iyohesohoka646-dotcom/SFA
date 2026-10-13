# Scientific workbench security review

The Codex Security Standard scan `825fd935-a5d1-4db8-a0fd-07ab8fe51636` completed against the saved `37a5516` plus initial task-6 working-tree snapshot. Its official report is preserved by Codex Security. The later fixes are a separate verification pass; the original report has not been rewritten to make them appear present in the scanned snapshot.

Of 442 ignore-aware inventory paths, 372 first-party source paths were fully audited. Seventy explicit exclusions include generated mixed vendor bundles and non-source artifacts. The result is partial repository coverage, not a complete third-party dependency or generated-bundle audit. Independent baseline and architecture passes contributed persistent evidence; the final scan records the snapshot change warning.

| Original finding | Effect and fix | Verification |
| --- | --- | --- |
| LOW: malformed or stalled pre-auth local collector peer | Could abort a real analysis during startup. Reject individual peers within bounded hello parsing/timeouts and continue waiting for the authenticated agent. | Four actual peer-first runs complete and preserve `X = 42`. |
| LOW: inherited capability-file permissions | Another local account with access to a readable project could obtain a service token. Restrict the parent and temporary capability file before writing, preserve restrictions across atomic replacement. | Real Windows ACL queries allow only owner/SYSTEM; POSIX checks require directory 0700 and file 0600. Studio and launcher callers are covered. |
| LOW: constant development fixture sessions | A public source constant authorized fixture execution. Generate a private per-run bearer and pass it through the environment; the profiler uses the same pattern. | Three browser listeners reject all former public bearers with 401; absent/malformed generated sessions are rejected. |

Seven Python boundary checks pass: six failed before repair, while the already-safe invalid-token case continued to pass. The three browser authorization regressions changed from an incorrect 200 to 401. These are tests of the local boundaries above, not a new full security scan of the final revision.

The final correctness review additionally exposed a queued-connection race: an authenticated independent producer may finish before collection begins. The corrected collector drains pending connections within its bounded accept deadline; a real TCP producer that exits first still preserves X=42. The earlier malformed/stalled-peer guards remain covered. POSIX interpreter validation also preserves the selected venv executable symlink rather than resolving it to the tool's base interpreter. These are post-scan regression fixes, not newly claimed scan coverage.

Clean installation also exposed an interpreter-isolation defect that editable-source tests did not catch. The chosen scientific Python now loads only the observation package through its standard-library bootstrap, instead of adding the tool's entire site-packages directory. A staged installed-package test rejects a peer tool-only dependency; the existing explicit local adapter test still discovers its opted-in plugin. Wheel/source acceptance verifies a selected interpreter without FastAPI or Pydantic.

This local application executes operator-selected scripts and explicitly enabled plugins with that operator's filesystem/network permissions. Observation budgets and subprocess boundaries are not an OS sandbox. External model tests use synthetic local servers; no real provider credentials or paid inference were used. Saved context/export privacy is exercised with synthetic sensitive values. Heuristic redaction has documented coverage limits.

The scan tool's usage report is rollout-aggregated: 33,301,873 input tokens, 183,337 output tokens, 33,485,210 total tokens, including 31,308,032 cached input tokens and 62,697 reasoning output tokens. It is not a measurement of net tokens spent on this task or a billing estimate.
