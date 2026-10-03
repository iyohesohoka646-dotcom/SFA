# Design, implement, run and review

Create a runnable starting point with `cdaf demo --target my-code --serve`. Studio opens the same project that the CLI uses. An empty project starts with `cdaf init --target my-code`; no implementation is invented until you create and review modules.

## Architecture

Define the project input schema, then give each module an object input contract, any JSON output contract and concrete input/output examples. A Python module points to a path and fully qualified function. New module acceptance creates a top-level skeleton if its source file is missing; a class/nested symbol must already exist in source. `scan` proposes source candidates for review and never assumes a call graph is an executable dataflow.

Bind required inputs explicitly. Choose project input, upstream module or literal/default, and set a JSON Pointer. Empty pointer means the whole value. Connecting an output to a port drafts a binding; if the target already has a writer, compilation reports a conflict. Use a merge module for multiple values. Binding visibility caps control AI context independently of execution. Advanced JSON editors expose grouping, Decision guards and composite output mappings.

A composite input appears to its immediate children as an upstream value from the composite `/port`; public output names map to immediate child outputs. External code connects to the public interface. The compiler checks declared contracts and expands mappings without losing hierarchy; complete public input/output objects are checked during execution. Collapsing and node position are view changes with separate revision checks.

**Validate** compiles the draft. **Review & save** creates a ChangeSet; inspect its diff, diagnostics and base version in **Review**, then accept. Invalid proposals cannot be accepted. If another process edits source or semantics during review, refresh and create a new proposal. Undo/redo affects the local draft; acceptance writes authored definitions transactionally.

## Implementation

Inspect **Context** or `cdaf context MODULE --level L2` to see the actual payload. Only approved upstream symbols and explicit dependencies can appear; a high requested level cannot override an edge's lower cap. Fixtures are sanitized. Model adapters do not get hidden source neighbors from a shared file.

Use a local candidate file or the offline mock to create an implementation proposal. Mock code only recognizes the supplied fixtures; unrecognized inputs raise an explicit error. For a general implementation, provide a normal Python function or configure an optional provider and an explicit model. Static validation enforces signature, decorators, imports, top-level structure and target-body ownership. It does not prove the function's business behavior; execute reviewed fixtures and probes to establish that evidence.

Review the candidate diff, then accept. The stored base file digest must still match. Accepted changes are recorded; **Propose rollback** creates a new inverse patch and protects unrelated edits. An external AI agent can also submit architecture JSON with `cdaf propose`; its filesystem permissions are managed outside CDAF.

## Execution and probes

Start a run with a JSON input file or Studio's input editor. Built-in examples offer success/failure buttons. Historical runs display the recorded graph and source/environment evidence, and the timeline limits display to events up to a chosen sequence. Designed edges and observed transfers are labeled separately. Static path focus answers reachability questions only.

Use probes for business assertions, metrics and bounded capture. `$input` and `$output` are typed roots; quote expressions correctly in a shell. Assertions must return bool, while evaluation errors remain error. BranchObserver displays hypothetical routing; a Decision with guards selects actual execution. A failed continuing assertion records quality failure without changing returned data. `block` prevents downstream work, `pause` requires explicit resume/cancel after a failure, and `breakpoint` pauses at the boundary.

Default evidence contains sanitized summaries. Authored `capture.level` can opt into sample or full data, with explicit bounds and retention. Check redaction/truncation/drop markers before interpreting a missing value. Pausing is at boundaries; cancellation terminates the owned worker process. Project code retains normal OS permissions.

## Share and reproduce

Export historical HTML, SVG, PNG, Mermaid or JSON. HTML opens offline, with search, node details and event replay; it does not rerun code. Each generated graphic has a geometry receipt; inspect exported Chinese glyphs and labels in a browser as well. Use `--run ID` to choose evidence explicitly; the default is the latest run.

The [three reference cases](examples/index.html) include source `flow.yaml`, Python implementations, input fixtures, event exports and a [validation record](examples/validation.json). Reproduce them with `python scripts/build_examples.py`. Edited reference files are preserved and regeneration refuses until reviewed. Rerunning side-effecting code always creates a new explicitly requested run.
