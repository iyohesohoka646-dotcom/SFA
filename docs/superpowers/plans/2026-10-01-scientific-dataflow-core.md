# 科研数据流核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立框架无关的科研数据观察协议，以 NumPy／pandas 首批适配器接入已有分析代码，生成有界、可信、可扩展的数据与运算观察记录。

**Architecture:** 新建独立科研领域模型、同进程采集代理和本地事件收集服务。显式 SDK 优先，选定源码的自动插桩作为可说明覆盖范围的增强模式；原分析进程保留原生数组和表格。旧 SFA 通过适配层读取，不要求科研脚本先定义端口图。

**Tech Stack:** Python ≥3.11；NumPy ≥1.26、pandas ≥2.2 作为科研环境能力；Pydantic 2 仅用于应用服务；SQLite；FastAPI；可选 Arrow IPC。

**Spec:** [SFA 科研数据流重构设计](../specs/2026-10-01-scientific-dataflow-refactor-design.md)。本计划覆盖 P0–P2，完成后进入统一工作台计划。

## Global Constraints

- 首版接入 NumPy／pandas 普通 `.py` 分析代码，不改变其对象、执行顺序、随机流和结果。
- 采集代理不能导入 Web 服务、旧调度器或终端 UI；依赖实际科研解释器里的 NumPy／pandas。
- 统计采样最多 4096 个元素，默认预览最多 32×32；切片响应最多 64×64。
- 默认发布间隔 100 毫秒，普通收集队列最多 2048 条；丢弃、截断和覆盖缺口必须可见。
- 默认完整采集关闭；开启后单产物 ≤64 MiB、单运行 ≤256 MiB，完整产物保留 7 天。
- 历史值必须绑定观察版本；仅元数据／样例采集不能被标成完整快照。
- 不使用 pickle，不打印未脱敏科研数据、凭据或任意用户对象的 `repr`。
- 保留用户代码和旧记录；迁移不自动重跑分析。

## Review Focus

- NumPy 视图、别名与原地修改：过去的样例不能随活对象变化；不支持的修改须报告覆盖限制，归任务 2、3。
- 作用域同名变量及循环：变量版本和操作次数必须区分，不能错误合并依赖，归任务 1、3。
- 非连续大数组、复数与 pandas 扩展类型：摘要不能隐式复制全矩阵或调用任意对象代码，归任务 2。
- 消费者断开或队列溢出：科研计算继续，关键错误不静默丢失，归任务 2、5。
- 慢／故障第三方探针：不得改变原分析数据和结果，需独立超时与状态，归任务 4。

## 文件边界

新建 `research/models.py`、`research/store.py`、`research/service.py`、`research/probes.py`、`research/legacy.py`；采集代理单独放在 `research/agent/`，包含 SDK、适配器、预算、传输与插桩。所有路径以 `src/contract_driven_ai_flow/` 为前缀。现有 `cli.py`、`api.py`、`workspace.py` 仅新增薄适配入口，直到新工作台可用再移除旧默认流程。

## Task 1: 核查基线并建立科研事件模型

**Files:**
- Create: `scripts/profile_interactions.py`, `docs/assets/research-baseline.json`
- Create: `src/contract_driven_ai_flow/research/models.py`, `research/store.py`
- Test: `tests/research/test_models_store.py`

**Interfaces:**
- Produces: `SourceRef`, `ValueDescriptor`, `SnapshotRef`, `OperationRecord`, `ObservationEvent`, `ProbeResult`，字段遵循设计第 4、7 节。
- Produces: `ExperimentStore(root: Path)`；`append(events: Sequence[ObservationEvent]) -> None`；`events(run_id: str, after: int=0, limit: int=1000) -> list[ObservationEvent]`；`runs() -> list[dict]`。
- 事件协议字段：`schema_version=1, run_id, sequence, kind, timestamp, source, operation_id, snapshot_id, payload`；依赖关系带 `observed / inferred / declared / unknown`。

- [x] **Step 1:** 复现当前按钮问题，保存逐操作 API、布局、首帧响应与状态变更记录；核对旧定义、运行和探针样本，写入基线，不能把静态源码猜测当成根因。
- [x] **Step 2:** 写 `test_scope_and_binding_versions_are_distinct`、`test_event_pagination_survives_restart`、`test_missing_full_snapshot_is_not_latest_value`，分别断言同名不同作用域独立、分页序号连续、未物化历史值明确不可用。
- [x] **Step 3:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_models_store.py -q`，确认因新模型／存储尚未实现而失败。
- [x] **Step 4:** 实现新模型与单独 SQLite 表，数据文件原子落盘；记录源码摘要、采集精度与覆盖状态，旧 `RunEvent` 不冒充科研事件。
- [x] **Step 5:** 同命令验证通过，核对重启和断页记录，提交 `feat: define scientific observation models and evidence store`。

## Task 2: 原生对象适配、SDK 与有界采集

**Files:**
- Create: `research/agent/{sdk,adapters,budget,transport,registry}.py`
- Create: `examples/research/custom-adapter.py`, `docs/research/adapter-api.md`
- Test: `tests/research/test_native_capture.py`, `tests/research/test_capture_budget.py`
- Create: `scripts/benchmark_research_capture.py`

**Interfaces:**
- Consumes: 任务 1 的事件协议；代理用标准库构造协议字典，不导入服务端模型。
- Produces: `TraceSession(name: str, transport: EventTransport, policy: CapturePolicy)`；`watch(name: str, value: object, *, source: dict|None=None, axes: tuple[str,...]|None=None, unit: str|None=None, parents: tuple[str,...]=()) -> dict`；`operation(label: str, *, inputs: Mapping[str,object]) -> ContextManager`。
- Produces: `describe(value: object) -> dict`；`capture(value: object, policy: CapturePolicy) -> CaptureResult`；`EventTransport.emit(event: dict, critical: bool=False) -> None`。
- Produces: `AdapterRegistry.register(adapter: DataAdapter) -> None`；`resolve(value: object) -> DataAdapter`；注册组 `cdaf.research.adapters`、协议 `version=1`。`DataAdapter` 提供 `supports/describe/capture`，描述符含扩展类型 ID 与能力列表；第三方插件显式启用，未知／延迟／设备对象不能隐式计算或复制。增加 `test_third_party_adapter_without_core_changes` 与 `test_unknown_lazy_value_does_not_compute_or_repr`。
- `CapturePolicy` 定义在 `research/agent/budget.py`：`level="summary", max_preview_cells=1024, max_stat_elements=4096, publish_interval_ms=100, max_queue_events=2048, max_artifact_bytes=67108864, max_run_bytes=268435456`；`CaptureResult` 定义在 `research/agent/adapters.py`，含 `descriptor, sample, statistics, fidelity, truncation, artifact_ref`。

- [x] **Step 1:** 写 `test_watch_preserves_array_identity_and_contents`、`test_observed_view_sample_is_frozen`、`test_large_strided_array_does_not_call_tolist_or_copy_full`、`test_complex_and_nullable_dataframe_have_typed_preview`、`test_queue_overflow_records_drops_and_preserves_terminal_event`。断言形状／dtype 真实、历史样例不变、总采样 ≤4096、预览 ≤1024 单元、不精确的统计显式标记。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_native_capture.py tests/research/test_capture_budget.py -q`，确认失败。
- [x] **Step 3:** 实现数值／表格适配、稳定样例、独立采样随机源、普通事件合并和关键事件通道；完整数值产物仅在明确策略下生成；不修改用户 RNG。
- [x] **Step 4:** 同命令通过；在固定 10 秒以上分析案例上运行 `scripts/benchmark_research_capture.py`，比较关闭采集／metadata／summary／full，记录中位额外耗时与峰值内存，SDK summary 目标 ≤5%。
- [x] **Step 5:** 提交 `feat: capture native scientific values with bounded probes`。

## Task 3: 普通脚本接入与覆盖可信的插桩

**Files:**
- Create: `research/agent/instrument.py`, `research/agent/runner.py`, `research/agent/source.py`
- Create: `src/contract_driven_ai_flow/templates/research-analysis/analysis.py`
- Test: `tests/research/test_instrumentation.py`, `tests/research/fixtures/*.py`

**Interfaces:**
- Consumes: `TraceSession` 与任务 1 协议。
- Produces: `instrument(source: str, filename: str, policy: InstrumentPolicy) -> InstrumentedCode`，包含编译对象、源码行映射及 `CoverageReport`。
- Produces: `run_script(path: Path, *, arguments: Sequence[str], session: TraceSession, policy: InstrumentPolicy) -> int`。
- `InstrumentPolicy`、`InstrumentedCode`、`CoverageReport` 定义在 `research/agent/instrument.py`；前者字段 `allowed_files, watched_names, watched_lines, capture_policy, mode`，后两者记录编译对象、源码映射与 `supported/partial/unsupported` 覆盖条目；不默认追踪第三方库源码。

- [x] **Step 1:** 写 `test_assignment_expression_is_evaluated_once`、`test_short_circuit_and_unpacking_keep_order`、`test_same_name_in_functions_has_distinct_scope`、`test_loops_keep_iteration_versions`、`test_inplace_array_mutation_is_versioned`、`test_uncovered_dynamic_code_is_reported`、`test_traceback_keeps_original_line`。与无插桩基线比较 ndarray、DataFrame、随机输出和原异常。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_instrumentation.py -q`，确认失败。
- [x] **Step 3:** 实现选定源码的内存 AST 变换和运行时绑定记录；保持原文件，记录实际输入快照及候选依赖。常见原地写入可观察，隐藏修改与动态代码报告未知；不能依赖全局 monkey-patch。
- [x] **Step 4:** 同命令通过；标准化／协方差／PCA 案例在成功、除零、维度错误下记录证据；自动 summary 开销目标 ≤20%，未达标则减少默认采集点并记录调试模式成本。
- [x] **Step 5:** 提交 `feat: observe existing Python analyses with explicit coverage`。

## Task 4: 可扩展科研探针与控制策略

**Files:**
- Create: `research/probes.py`, `research/probe_worker.py`, `research/probe_registry.py`
- Test: `tests/research/test_scientific_probes.py`, `tests/research/test_probe_isolation.py`
- Create: `docs/research/probe-api.md`

**Interfaces:**
- Consumes: `ValueDescriptor`、`SnapshotRef` 与有界样例。
- Produces: `ProbeContext`、`ProbePlugin.evaluate(context: ProbeContext) -> ProbeResult`。
- Produces: `evaluate_probe(spec: ProbeSpec, snapshot: SnapshotRef, *, budget_ms: int=50) -> ProbeResult`。
- 插件注册组：`cdaf.research.probes`；协议 `version=1`。状态 `pass/fail/error/skipped/unknown`，精度 `exact/sampled/metadata_only`。

- [x] **Step 1:** 写 `test_sampled_finite_check_does_not_claim_full_pass`、`test_shape_and_broadcast_diagnostics_use_real_dimensions`、`test_custom_probe_cannot_mutate_analysis_array`、`test_slow_probe_times_out_without_stopping_analysis`、`test_expensive_rank_probe_requires_explicit_enable`。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_scientific_probes.py tests/research/test_probe_isolation.py -q`，确认失败。
- [x] **Step 3:** 实现首批形状、dtype、有限值、范围、缺失、方差、对称性与性能探针；自定义插件只收到脱敏、有界对象，采用最多 2 个工作进程的复用池。进程启动单独限时 3 秒，求值预算默认 50 ms，探针排队不阻塞分析；暂停／取消走独立控制记录。
- [x] **Step 4:** 同命令通过；用示例插件验证无需修改核心即可注册，记录依赖、预算和不支持的输入。
- [x] **Step 5:** 提交 `feat: add isolated scientific probe plugins and controls`。

## Task 5: 统一研究服务、基础 CLI 与旧证据迁移

**Files:**
- Create: `research/service.py`, `research/routes.py`, `research/legacy.py`
- Modify: `src/contract_driven_ai_flow/{cli,api,workspace}.py`, `pyproject.toml`
- Test: `tests/research/test_service_cli.py`, `tests/research/test_legacy_import.py`
- Create: `docs/research/quickstart.md`

**Interfaces:**
- Produces: `ResearchService(root: Path)`；`start_analysis(script: Path, *, interpreter: Path, arguments: Sequence[str]=(), mode: str="summary") -> RunHandle`；`cancel(run_id: str) -> None`；`get_snapshot(snapshot_id: str) -> dict`；`slice(snapshot_id: str, selectors: Sequence[dict]) -> dict`；`events(run_id: str, after: int=0, limit: int=1000) -> list[dict]`。
- `RunHandle` 定义在 `research/service.py`，字段 `run_id, status, interpreter, source_digest, capture_mode`；`MigrationReport` 定义在 `research/legacy.py`，字段 `source, destination, original_ids, converted_items, unsupported_items, warnings, applied`。
- HTTP：`/api/v1/research/runs`、`/runs/{id}/events`（可续接 SSE）、`/snapshots/{id}`、`/snapshots/{id}/slice`、`/runs/{id}/cancel`、`/probe-types`。客户端协议在工作台任务中生成类型。
- CLI：`cdaf observe <script> --python <path> --capture summary`、`cdaf research runs`、`cdaf research inspect <snapshot>`、`cdaf research export <run>`。提供 `--json`；成功 0、分析失败 1、配置／用法错误 2、取消 130。
- Produces: `import_legacy(source: Path, destination: Path, *, preview: bool=True) -> MigrationReport`，保留原 ID 与原语义，缺失研究字段标为未采集。

- [ ] **Step 1:** 写 `test_cli_and_http_share_snapshot_semantics`、`test_stream_resumes_without_duplicate_events`、`test_selected_interpreter_is_used`、`test_missing_history_slice_is_unavailable`、`test_viewer_disconnect_does_not_block_analysis`、`test_cancel_flushes_terminal_state`、`test_legacy_import_preserves_source_and_ids`。
- [ ] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_service_cli.py tests/research/test_legacy_import.py -q`，确认失败。
- [ ] **Step 3:** 实现服务命令、解释器探测、采集代理启动与来源校验；所有客户端调用该服务；批量持久化事件，不在每次读取时重新扫描整个定义。旧项目迁移先预览、写新目标并保存报告。
- [ ] **Step 4:** 同命令通过，执行自己的 `.py` 案例并用 CLI 检查真实矩阵与失败来源；保留旧相关回归测试；停止／异常退出后记录可解释。
- [ ] **Step 5:** 提交 `feat: expose scientific observation service and command line`，固定协议和示例，然后进入工作台计划。

## 交付门槛

科研核心必须独立运行：不启动浏览器也能观察分析脚本、查看真实摘要、解释故障并导出证据。NumPy／pandas 和第三方适配器均通过同一接口验证。通过核心正确性与默认开销检查后才开始将它接入新默认工作台。用户已授权完整建构，复选框按实际验证结果更新。
