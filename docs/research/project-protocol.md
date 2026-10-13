# Project protocol and extension boundaries

All project requests use `/api/v1/research/projects/{project_id}/…`; no backend ambient active-project variable is used. Generated models are in `schemas/projects.json` and `web/src/research/projects/generated.ts`. Run `scripts/export_schema.py` and `npm run types --prefix web` after Python wire-model changes.

| Component | Responsibility |
| --- | --- |
| `projects/service`, `discovery`, `resolver`, `store` | inert discovery, per-file analysis, imports/symbols and published revision archives |
| `projects/application`, `runtime`, `workbench`, `agent/project_runner` | frozen entry and source verification, normal import-loader delegation, one bounded evidence session |
| `projects/queries`, `graph_projection`, `routes` | paged objects/references, scoped Code/Data projections and HTTP adapters |
| `projects/intelligence*`, `context_tools` | explicit project/range authorization, versioned tool evidence and model task budgets |
| `projects/changes`, `change_routes` | create/edit proposals, complete preflight, staged per-file writes and recoverable journals |
| `ProjectHost`, `ResearchServices`, `ProjectWorkbench` | one UI project, immutable scoped clients, shared selection and docked documents |

Project, file, logical object and execution instance IDs remain separate. A source digest and project revision accompany source/data references. Calls connect resolved arguments, parameters and returns; unresolved dynamic targets remain unknown. Import graphs may contain cycles. Scope is resolved before visible-unit limits; folded edges retain original IDs and boundary metadata.

Read endpoints include `tree`, `objects`, `source`, `analysis`, `symbols`, `references`, `graph`; long indexing and execution operations return durable task records. Writes and plans carry expected versions and return conflicts rather than silently replacing state. Script and module entries retain Python argv, cwd, package, relative import and import-cache semantics. Custom loaders/third-party source are delegated with explicit coverage gaps.

Probe definitions, templates and applied instances use the existing common protocol. Project, directory, file, function and object selectors freeze into concrete targets at planning. Evidence-only plans use archived run entry/inputs plus explicitly frozen current probes; they never mutate the original run plan. Folder and cross-file ownership is already supported; new block providers and overlapping branch memberships should implement the same member/source references rather than merge files into a giant analysis document.

Cross-file changes support create and edit only. No automatic rename/delete, execution, or claim of simultaneous multi-file filesystem atomicity is made. Index publication shares the change lock, preventing a half-written revision. Active jobs/watchers prevent root relocation; idle relocation rebuilds cached stores. Cancellation after durable acceptance records the actual committed result and revision.

Private interpreter paths, environment values and credentials live on the host. Public plans retain symbolic references and random snapshot IDs. Display relationships do not grant model read access. Redaction precedes archives, browser delivery and model context. Historical missing archives and unknown coverage remain explicit errors/markers.
