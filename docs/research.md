# Sources and implementation choices

The scientific 0.4 workbench builds on the retained architecture runtime. See [scientific workflow](research/workbench.md) and [automatic harness](architecture/scientific-harness.md). Data presentation itself is a probe; view/check/interpret remain distinct from program/model/Skill/manual execution. Parsing and configuration are inert, computation and rendering explicitly requested, code acceptance remains human controlled.

The research baseline is [SFA c9a745e](https://github.com/iyohesohoka646-dotcom/SFA/tree/c9a745e851d155b4c5fdede2d6cd2758c530e3c0); the visual reference is [Archify a07fa1d](https://github.com/tt-a1i/archify/tree/a07fa1d5b2a10cbea110c5a2be2817397a301cdc). The optional adapter checks that exact Archify commit. Comparisons concern specific useful mechanisms, not interchangeable products.

| Source | Useful mechanism | CDAF implementation |
|---|---|---|
| [Archify](https://github.com/tt-a1i/archify) | Typed diagram IR, strict visual checks, portable viewers, source/proof artifacts | Versioned exports, design/evidence labels, geometry receipts, case gallery, pinned optional renderer |
| [LikeC4](https://github.com/likec4/likec4) | Multiple views over a semantic architecture model | Shared model, hierarchy, local focus, independent view state |
| [Apache Hamilton](https://github.com/apache/hamilton) | Python function dataflow and execution/data lineage | File-qualified functions, explicit data bindings, attempt/transfer evidence |
| [NoFlo](https://github.com/noflo/noflo) | Public ports/subgraphs and editor/runtime separation | Composite public maps, compiled graph, CLI/API/Studio adapters |
| [Node-RED debug sidebar](https://nodered.org/docs/user-guide/editor/sidebar/debug) | Filtering node observations and inspecting payloads | Node/edge probes, result sidebar and bounded captures |
| [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/) | Attempt spans, events and links for causality | OTLP/JSON and caller-configured optional SpanExporter |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | Current specifications distinct from change proposals | Inert ChangeSet review/apply flow and acceptance history |

SFA's original loop of authored structure, contract-constrained implementation and runtime observation is retained. Replacements address concrete weaknesses: implicit field overwrites become explicit bindings; nested alias sharing becomes JSON process transfer; whole-file L4 context becomes authorized symbol context; line replacement becomes AST checks plus LibCST; group-only composites become actual public interfaces; observational Router semantics become clearly distinct from actual Decisions; cleanup preserves authored definitions.

[LangGraph conditional edges](https://docs.langchain.com/oss/python/langgraph/graph-api#conditional-edges) can use ordinary deterministic functions. CDAF does not distinguish itself by claiming an LLM is required for another system's routing. Its emphasis is human-authored code boundaries, reviewed implementation patches and visible revision-bound evidence.

[CEL's design](https://cel.dev/overview/cel-overview) informs compile-once, bounded evaluation; the current Python AST expression subset is versioned and limited, and is not advertised as CEL-compatible. [React Flow's layout guidance](https://reactflow.dev/learn/layouting/layouting) supports using an external layout engine; ELK handles ports while the application owns semantic grouping and saves views independently. [OpenTelemetry's sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/) informs sanitization before evidence persistence and export; authored source/recovery content must still retain exact values to be applied faithfully.

The implemented graph viewer supports search, reachability focus, deep links, collapsed groups, themes and event-based historical playback. It does not claim Archify's complete route/story/viewer toolset. Archify remains optional, so editing and executing a Python project never depends on its Node renderer.
