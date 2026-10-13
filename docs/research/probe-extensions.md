# Probe extensions and shared workbench commands

Probe capabilities and installed resources are separate from configured
instances. Organize resources by target (data, operation, function, control,
file/project), purpose (view, check, interpret, derive), and implementation
(builtin, program, model, Skill, manual). A program or Skill can serve multiple
purposes. Installed plotting packages remain independent of the public catalog.

```powershell
cdaf --json workbench import analysis.py --project .
cdaf --json workbench settings --project .
cdaf workbench resources --import resource.json --project .
cdaf workbench resources --enable laboratory --project .
cdaf workbench bind --input instance.json --project .
cdaf workbench scope ANALYSIS_ID --selector scope.json --project .
cdaf workbench plan ANALYSIS_ID --target-scope scope.json --project .
cdaf workbench run --plan PLAN_ID --project .
cdaf workbench probes --run RUN_ID --evaluate --project .
cdaf workbench derived DERIVED_ID --proposal --project .
cdaf workbench changes --proposal PROPOSAL_ID --action accept --project .
cdaf workbench migrate-config --project .
cdaf workbench migrate-config --apply --project .
```

The existing `cdaf research` commands remain compatible. Plans freeze target
references, definition/configuration versions, input evidence, meaning and
capture/concurrency preferences. Joint instances use `inputs` roles with exact
snapshot references, while compute plans resolve logical targets in the new run.
Foreign-run joint evidence requires `allow_cross_run: true`; per-object checks
cannot silently use foreign evidence. Complete data missing or expired requires
a new capture run.

A resource manifest declares its version, definitions, parameter JSON Schema,
entry, input roles, supported targets/types and evidence requirements. See the
program case’s manifest and `lab_probe.py`. Its `evaluate(context, parameters)`
receives frozen, sanitized target/evidence dictionaries and returns an explicit
status plus optional message/data. It runs in an owned worker with a timeout and
output budget. Enabled local source is hashed; changes after review produce an
error. Programs inherit the selected interpreter’s filesystem/network rights;
process isolation is not a filesystem sandbox. Transitive imported modules are
not individually hashed. Package/environment versions are checked for compute.

Resource updates are staged separately; the old installed version remains live
across restart until the draft is explicitly enabled. Import never invokes an
entry. Rendering code and model calls require an execute action. Default data
views are ordinary visible instances: stopping or deleting one persists, and
closing a tab keeps its instance enabled. Custom program view results are shown
as structured output; use the renderer registry or a plotting adapter for richer
frontend visualizations.

`tools --scan` detects distribution versions without importing plotting modules.
`tools --describe matplotlib` explicitly runs bounded isolated signature/doc
introspection for supported public methods. The assistant can use
`tools.describe` and `resource.propose` to draft adapters; it cannot enable them.
Public adapters currently implement Matplotlib, Seaborn, Plotly and Altair;
Bokeh, PyVista and HoloViews are catalog candidates and need an adapter.

Meanings/units/coordinates distinguish program, user and model origins. Model
suggestions must be accepted before joint calculations use them. Coordinate
lengths and table column definitions are checked against observed shape.

Saved derived analyses retain their complete parents until explicitly released.
`derived --release` removes this retention lease, keeping history and definitions.
`expire` applies the configured retention period only to unretained expired bulk
artifacts. Generated code proposals are pure numerical kernels with evidence
references; the workbench still owns version, coordinate and capture-budget
checks. Accepting a proposal writes a separately reviewed new file.

Protocol v2 migration preserves exact bytes in `workbench.yaml.v2.bak`, deleted
defaults and IDs. Ambiguous name bindings become disabled pending rebinding.
Old plans must be prepared again. Historical graphs use saved analysis/source
versions; redacted or unverifiable archived source is reported unavailable.
Pre-Dockview layouts are retained in browser storage before conversion, with an
explicit restoration action. Evidence missing coordinate metadata cannot be used
for a coordinate-dependent table join.

The frontend `renderer-registry.ts` and the backend adapter/probe catalogs are
separate extension points. `MemberBlockProvider` accepts graph member references
and overlapping stream membership; see the provider example. Folder providers
and cross-file parsing are contracts, not active import buttons in this release.
