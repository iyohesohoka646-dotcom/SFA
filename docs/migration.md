# Migrating SFA projects

Migration reads the original project and writes only to a separate empty destination. Original definitions, code and snapshots remain untouched. Preview first:

```console
cdaf migrate path/to/old --destination path/to/new
cdaf migrate path/to/old --destination path/to/new --resolutions bindings.json --apply
cdaf check --project path/to/new
cdaf studio --project path/to/new
```

`bindings.json` explicitly resolves ambiguous target ports:

```json
{
  "consumer.value": {"kind": "module", "module": "producer_a", "pointer": "/value"}
}
```

The report lists unresolved bindings, invalid references/schemas and compiler diagnostics. Multiple upstreams with the same field cannot be resolved by visual/declaration order. A known unique output property may be mapped; unknown shapes require a user-authored source. Project inputs and literal defaults are equally explicit. Issues prevent application, and an occupied destination is never overwritten.

The new project stores authored data in `flow.yaml` and `flow/`; `.cdaf/` contains runtime evidence. A `legacy/` backup retains original `.sfa/` and source metadata. It may contain original secrets and is ignored by the migration's Git configuration. Old snapshots preserve original IDs/semantics in sanitized migrated artifacts, marked `legacy` / unknown-version evidence; they are not presented as freshly executed CDAF runs.

Old Router probes become read-only BranchObservers. They cannot control actual branching. Convert intended branching explicitly to Decision/RouteGuard architecture and verify both selected and skipped outcomes. Historical composite groupings are retained in migration provenance; their former raw cross-group connections are flattened with a warning. Restoring a public composite interface is an explicit reviewed edit, since the old format did not define trustworthy port mappings.

`sfa` aliases the new CLI for one major version. Access old commands with `sfa legacy ...` or `python -m sfa ...`. Both new and legacy clean entry points preserve architecture definitions; the legacy path only clears its extraction cache. `examples/pipeline/demo.py` remains a legacy compatibility example and now preserves existing probes when repeated.
