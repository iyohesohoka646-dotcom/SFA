# Scientific workbench 0.4 review

Fresh reviewer: GPT-6 Astra, independent context. Reviewed the new hand-written boundaries in 2889954..ccc8851 and the distribution-version follow-up c2647fa. Generated/minified assets were excluded from source judgment. One material fix pass follows this review; no second reviewer is dispatched.

## Material findings

1. Redacted assignment fragments could corrupt a reviewed rollback. Recover the original fragment only from digest-verified raw source; never persist secret-bearing rollback text.
2. Constructing a second CLI job manager could interrupt a live Web task. Persist process identity and recover only dead owners.
3. Worker stdout/stderr limits were applied after exit. Bound collection during execution and terminate the owned process tree on overflow.
4. Cancelling a historical probe task poisoned its run's shared probe pool. Cancel the task's own workers, preserving concurrent/retry tasks on that run.
5. A model final answer could be accepted after its source changed. Recheck the frozen source digest at each response.
6. A pinned data view evaluated the global run instead of its immutable run. Carry the snapshot reference through the action.
7. A pinned graph went empty when the global run changed. Preserve its loaded graph and camera while loading its own historical evidence.
8. Pause policies had no resume action in the new UI. Expose paused state, its failed gate and an explicit continuation control.
9. Automatic snapshot model probes could read unrelated sibling bodies. Derive the smallest declared source boundary and direct dependencies from evidence; unmatched evidence grants no source reads.
10. Migrated wildcard bindings such as X* silently produced no results. Restore matching semantics in historical postprocessing.

Regraded from Minor to Important: requested Plotly/Altair line/histogram could silently render a heatmap. Shipping a different chart with a success status changes the scientific meaning; adapters must honor supported kinds or reject them.

Additional user feedback: the matrix canvas compressed close large positive values into the same green and hid all scale/fidelity notes. Default to the displayed finite range, provide a compact numerical legend, missing/nonfinite keys and original row/column indices; constant data explicitly says it is constant. Rare statistics and capture details remain collapsible.

## Deferred minors

- Source object text is capped at 16 KiB without a separate per-object truncation flag. A large symbol's line range can exceed its returned source excerpt.
- An invalid CLI ask role raises an unhandled StopIteration rather than a friendly argument error. Documented roles continue to work.

## Review boundaries and executor rulings

- Remote model quality/performance is unverified. Actual HTTP tool-loop fixtures and offline behavior are covered; no paid provider inference is claimed.
- Final Windows delivery belongs to executor acceptance. The source reviewer does not attest to a packaged binary; release statements require a current native receipt.
- Bokeh/PyVista/HoloViews and arbitrary graph wire editing remain extension candidates, as documented; automatic package detection does not implement an adapter.
- Older runtime paths are retained and covered by the regression suite, with the fresh review focused on new boundaries; this is not a renewed exhaustive audit of all legacy code.

Backend review regressions: 36 passed after observed failures; complete Python suite: 573 passed. Frontend units: 20 passed; complete real browser suite: 45 passed, including the four original UI reproductions and two additional delivery/status boundaries. The final native/bundle receipt is recorded separately in release.md and its linked artifact.

Additional material boundaries found during executor delivery: toolbar replot incorrectly scoped to the selected value, completed tasks could leave a stale running indicator, and pip --upgrade retained older same-version desktop package bytes. Each was reproduced before its correction; the exact wheel, copied runtime and source archive's 221 package resources were compared directly.
