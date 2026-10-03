# Scientific task harness

The scientific service owns task-scoped source objects, evidence and capabilities. The browser and CLI submit a task with a focus and role; they do not build a hidden selection checklist for the model. The initial manifest describes the selected interpreter, available tools, public plotting catalog, object inventory and versioned focus. Subsequent reads use registered tools. Source, guidance and Skill text are task material and cannot add capabilities.

The bounded JSON tool loop works through the existing OpenAI-compatible and Anthropic text adapters. A role selects the provider/model, input/output budgets and allowed effects. Every actual request, usage receipt, tool request, result and citation is recorded after redaction. The UTF-8 byte estimate is a conservative token bound; it is not an exact tokenizer count. Source digests are checked before reads. Offline analysis remains explicitly offline. A model can propose code but has no acceptance tool.

Architectural references were inspected on 2026-10-02:

- [DeepSeek Harness agent API](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent/README.md): scoped registration and lifecycle separate from the loop driver. The workbench keeps scientific services independent of the model loop.
- [DeepSeek agent loop](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent-loop/README.md): identifiable requests and cancellation inspire the call receipts and task ownership here.
- [Kilo instruction context](https://github.com/Kilo-Org/kilocode/blob/main/packages/core/src/instruction-context.ts): environment context is a registered, refreshable source. Here project guidance is bounded to the chosen project.
- [Codex project instructions](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs): source provenance, project boundaries and bounded reads inform the guidance manifest.

This is an application-specific harness, with no shell or arbitrary filesystem tool. It does not embed those projects or claim their full agent functionality. Local analysis/drawing subprocesses retain their interpreter's filesystem and network permissions; process isolation is not an operating-system security sandbox. New backends and extensions must explicitly register capabilities.
