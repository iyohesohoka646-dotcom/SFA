# 科研工作台与统一入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将科研数据流核心交付为响应及时、模型设置可发现、启动与关闭一体的 Web／桌面／终端产品。

**Architecture:** 三种客户端共用科研应用服务、事件协议、数据版本和配置。重写前端默认主流程，以源码、当前数据和局部运算链为中心；桌面只增加窗口与生命周期管理。长任务独立运行，每项操作有自身状态与取消入口。

**Tech Stack:** TypeScript、React、React Flow、ELK Web Worker、Canvas；Textual 交互终端与 Typer CLI；FastAPI；Electron 桌面外壳（原计划 Tauri 2，见发行审查中的技术裁决）；系统凭据库。

**Spec:** [SFA 科研数据流重构设计](../specs/2026-10-01-scientific-dataflow-refactor-design.md)。依赖 [科研核心计划](2026-10-01-scientific-dataflow-core.md) 的事件协议和 `ResearchService`；覆盖 P3–P5。

## Global Constraints

- 一个本地应用服务、一个事件与数据协议、三种客户端；首版仍为本地部署。
- 基础观察、热图和探针不依赖模型或 API Key，默认不发送全量科研数据。
- 默认最多 80 个可见节点；数值更新不触发图布局，历史与矩阵按需读取。
- 矩阵预览最多 32×32，切片响应最多 64×64；不把抽样图标为精确全矩阵。
- 1000 个逻辑值／80 个可见节点／10000 条事件下，搜索、选择和切换 p95 首次视觉响应 ≤100 ms，详情 ≤250 ms。
- 服务已就绪后首页 ≤2 秒可交互，历史及矩阵按需加载。
- 10 次更新／秒时发布至可见 p95 ≤250 ms，10 分钟内存不随事件数无界增长。
- 密钥由后端管理，配置仅保存引用；浏览器读取接口、事件、导出和 AI 上下文不返回密钥。
- 默认桌面关闭拥有的服务；浏览器最后一个标签正常退出后 3 秒停止，崩溃租约超时 120 秒。
- 用户独立 CLI 启动的任务不能因关闭查看窗口被停止；显式后台模式状态可见。

## Review Focus

- 快速切换变量／运行、并发请求乱序：旧响应不得覆盖新选择，归任务 1、2。
- 成千上万次更新与事件分页：不重新全图布局，不以无界数组保存全部历史，归任务 1、2。
- 密钥更新、连接失败、取消与慢模型：基础数据查看仍可用，敏感内容不泄漏，归任务 3。
- 窗口启动中关闭、重复启动、多标签刷新、后台标签与崩溃：进程所有权及清理必须准确，归任务 5。
- 无终端／无模型／独立 Python 环境的干净安装：三个入口有明确恢复路径，归任务 4、6。

## 文件边界

`web/src/App.tsx` 重写为页面编排；领域状态位于 `web/src/research/`，不把所有事件、画布、编辑器和模型表单塞回一个组件。`web/src/settings/`、`web/src/runtime/` 分别管理配置和生命周期。Python 新建 `application/` 共享命令服务、`terminal/` 终端客户端和 `settings/`。`desktop/` 只维护桌面外壳。

## Task 1: 客户端状态、异步操作与性能回归基线

**Files:**
- Create: `web/src/research/{client,state,selectors,operations}.ts`
- Modify: `web/src/{App,Workspace}.tsx`, `web/src/api.ts`, `web/src/graph.ts`, `web/package.json`
- Test: `web/tests/research-performance.spec.ts`, `web/tests/research-state.test.ts`
- Create: `scripts/profile_research_workbench.py`

**Interfaces:**
- Consumes: 核心的 `ObservationEvent`、`ValueDescriptor`、`SnapshotRef` 与 HTTP／SSE 路由，生成 TypeScript 类型。
- Produces: `applyEvent(state: ResearchState, event: ObservationEvent): ResearchState`；`selectVariable(state, bindingId): VariableView`；`useOperation(key: string): {status, run, cancel}`。
- `ResearchState`／`VariableView` 定义在 `state.ts`／`selectors.ts`；`useOperation` 定义在 `operations.ts`；`web/package.json` 增加 Vitest 的 `test` 脚本，现有 Playwright `test:e2e` 保留。
- 状态按 run／snapshot／operation ID 归一化，事件和探针建立索引；每个异步请求包含选择版本并可被取消。

- [x] **Step 1:** 写乱序选择、重复事件、布局次数、慢请求不阻塞搜索四项回归；Playwright 场景使用 1000 个逻辑值、80 个可见节点、10000 条事件并连续输入／快速点击。
- [x] **Step 2:** 运行 `npm test --prefix web -- research-state` 和 `npm run test:e2e --prefix web -- research-performance`，确认当前方案失败并保留 trace。
- [x] **Step 3:** 建立增量索引、分页历史、独立请求状态和取消；去掉每次渲染的整模型 JSON 比较、逐节点全事件扫描和全局 `busy` 阻塞；仅拓扑／展开状态变化触发布局。
- [x] **Step 4:** 同命令通过，记录响应 p50／p95、长任务、重绘与 API 耗时；预算未达标则调整渲染范围，不能只增加测试等待时间。
- [x] **Step 5:** 提交 `refactor: decouple scientific state updates from rendering and layout`。

## Task 2: 矩阵、表格、源码与局部运算链

**Files:**
- Create: `web/src/research/{ResearchWorkbench,SourcePane,VariableList,MatrixView,TableView,OperationView,ProbePanel,RunTimeline}.tsx`
- Create: `web/src/research/{matrix-renderer,explanation-templates}.ts`, `web/src/research/research.css`
- Modify: `web/src/{App,Workspace}.tsx`
- Test: `web/tests/research-workbench.spec.ts`, `web/tests/research-matrix.spec.ts`

**Interfaces:**
- Consumes: 任务 1 归一化状态与核心 `get_snapshot`／`slice`。
- Produces: `MatrixView({snapshot: SnapshotRef, selectors, onSelect})`；`OperationView({operation: OperationRecord, snapshots})`；`explainOperation(operation, descriptors): Explanation`。
- 未保存的历史完整值显示“此版本未保存完整数据”，高维切片明确固定轴，抽样图有方法和精度标签。

- [x] **Step 1:** 写真实标准化／协方差／PCA 案例的源码跳转、shape 改变、历史切片不可用、NaN 来源定位、探针添加；补充复数、空矩阵、重复索引、无轴语义和中文注释用例。
- [x] **Step 2:** 运行 `npm run test:e2e --prefix web -- research-workbench research-matrix`，确认功能尚不存在而失败。
- [x] **Step 3:** 实现四区域工作台、Canvas 热图、虚拟化变量／表格列表、局部数据流与游标时间线；基础运算使用规则解释，未证实的单位／实验意义保持未知。首页直接打开代码与选择环境。
- [x] **Step 4:** 同命令通过；真实操作打开自己的脚本、启动分析、选矩阵、固定轴、追踪上游、定位故障；验证键盘、中文、低动效和错误恢复，重新测量任务 1 的性能预算。
- [x] **Step 5:** 提交 `feat: inspect scientific matrices and transformations in the workbench`。

## Task 3: 全入口模型设置与有证据的解释

**Files:**
- Create: `src/contract_driven_ai_flow/settings/{models,credentials,service,routes}.py`
- Create: `web/src/settings/{ModelSettings,ProviderForm,ModelPicker}.tsx`
- Modify: `src/contract_driven_ai_flow/{providers,cli}.py`, `web/src/research/OperationView.tsx`
- Test: `tests/research/test_model_settings.py`, `tests/research/test_explanation_privacy.py`, `web/tests/model-settings.spec.ts`

**Interfaces:**
- Produces: `ProviderProfile`，字段 `id, protocol, base_url, models, default_model, timeout_seconds, credential_ref`；公开状态另含 `configured`，不含密钥。
- Produces: `ModelSettingsService.list() -> list[PublicProviderProfile]`；`save(profile: ProviderProfile, secret: str|None=None) -> PublicProviderProfile`；`test(profile_id: str, *, inference: bool=False) -> ConnectionResult`。
- Produces: `ExplanationService.explain(operation_id: str, *, provider_id: str, model: str, include_sample: bool=False) -> Explanation`。
- HTTP：`/api/v1/settings/models`、`/settings/models/{id}/test`、`/research/operations/{id}/explain`；CLI `cdaf models list/configure/test` 与后续 `/model` 共用服务。

- [x] **Step 1:** 写 UI 明显入口、模型可搜索与手填、保存后 CLI 同步、连接失败／取消、密钥不回读、无凭据库不落明文、默认只发送源码与脱敏摘要用例；用本地假模型服务验证协议，不调用用户现有真实凭据。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_model_settings.py tests/research/test_explanation_privacy.py -q` 和 `npm run test:e2e --prefix web -- model-settings`，确认失败。
- [x] **Step 3:** 实现系统凭据引用、OpenAI-compatible／Anthropic 配置、离线规则模式、连通性与推理测试的不同标签；模型解释显示发送范围、用量与取消，输出区分事实和推测。
- [x] **Step 4:** 同命令通过；慢模型测试期间搜索、矩阵切片、探针与取消均可用；实际付费服务验证仅在用户明确配置及授权之后进行，不以假服务结果宣称真实服务已验证。
- [x] **Step 5:** 提交 `feat: unify discoverable model settings and evidence-based explanations`。

## Task 4: Codex／Kilo 风格的交互 CLI

**Files:**
- Create: `src/contract_driven_ai_flow/terminal/{app,commands,views,client}.py`
- Create: `src/contract_driven_ai_flow/application/commands.py`
- Modify: `src/contract_driven_ai_flow/cli.py`, `src/contract_driven_ai_flow/research/routes.py`, `pyproject.toml`
- Test: `tests/research/test_terminal.py`, `tests/research/test_command_parity.py`
- Create: `docs/research/cli.md`

**Interfaces:**
- Produces: `dispatch(command: str, arguments: dict, *, service: ResearchService, settings: ModelSettingsService) -> CommandResult`；Web 动作与 CLI／TUI 复用此层。
- Produces: `ResearchTerminal(service_client: ResearchClient)`；`/open /run /vars /probe /model /help /quit`。
- `ResearchClient(base_url: str, token_ref: str)` 定义在 `terminal/client.py`，异步包装 HTTP／SSE 的 `command(name: str, arguments: dict) -> CommandResult` 与 `events(run_id: str, after: int=0) -> AsyncIterator[dict]`；`CommandResult` 定义在 `application/commands.py`，含 `status, data, error, run_id`，错误不包含凭据和原始数据。
- `cdaf` 在 TTY 进入交互界面；非 TTY 输出帮助，`--help` 和 `--json` 不进入 TUI。长任务后台执行，Ctrl+C 取消当前任务，再次退出恢复终端状态。

- [x] **Step 1:** 写 TTY／管道入口分流、命令发现、实时变量索引、运行恢复、模型配置共享、慢任务期间可输入、取消后终端恢复，以及 Web／CLI 相同动作产生相同事件用例。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_terminal.py tests/research/test_command_parity.py -q`，确认失败。
- [x] **Step 3:** 实现 Textual 界面与共享命令调度；按 Codex 事件／输入分工和 Kilo 模型发现机制组织交互，终端展示有界摘要和必要状态，不强行在字符终端复制完整热图。
- [x] **Step 4:** 同命令通过；在真实 PowerShell 终端验证运行、输入、取消、模型选择、帮助和退出；保留 Typer 自动化命令的相关测试。
- [x] **Step 5:** 提交 `feat: add an interactive scientific terminal sharing application services`。

## Task 5: 单入口桌面、浏览器租约与退出清理

**Files:**
- Create: `desktop/src-tauri/{Cargo.toml,tauri.conf.json,src/main.rs,src/backend.rs}`
- Create: `src/contract_driven_ai_flow/application/lifecycle.py`, `web/src/runtime/{lifecycle,service-status}.ts`
- Modify: `src/contract_driven_ai_flow/{studio,launcher,shortcuts}.py`
- Test: `tests/research/test_lifecycle.py`, `web/tests/lifecycle.spec.ts`, `desktop/tests/lifecycle.spec.ts`
- Modify: `docs/local-deployment.md`

**Interfaces:**
- Produces: `BackendOwner.start() -> ServiceHandle`；`BackendOwner.stop(*, cancel_owned: bool=True) -> None`；状态 `starting/ready/error/stopping/stopped`。
- Produces: `ClientLease.acquire(client_id: str) -> Lease`；`release(lease_id: str) -> None`；`renew(lease_id: str) -> None`。正常最后退出宽限 3 秒，异常租约 120 秒；使用实际连接状态，不能只依赖后台 JS 定时器。
- 桌面、浏览器拥有服务与连接已有后台服务分开；独立 CLI 运行拥有自己的执行归属。重复启动复用窗口／已有服务，启动中退出能取消准备并清理已启动子进程。

- [x] **Step 1:** 写正常关闭、启动中关闭、重复启动、失败后重试、最后标签关闭、多标签、刷新、背景标签、崩溃回收、独立 CLI 任务继续，以及证据落盘／端口释放用例。
- [x] **Step 2:** 运行 `.venv\Scripts\python.exe -X utf8 -m pytest tests/research/test_lifecycle.py -q`、`npm run test:e2e --prefix web -- lifecycle` 与桌面生命周期测试，确认当前双快捷方式和持续服务行为不满足新默认而失败。
- [x] **Step 3:** 实现 Tauri 所有权控制、单入口快捷方式和窗口状态；普通 Web 加入租约及“退出并停止”操作；`cdaf serve` 作为显式后台服务入口。停止先取消拥有的任务、落盘，5 秒后再终止尚未响应的拥有子进程，残留问题记录为错误。
- [x] **Step 4:** 同命令通过；实际关闭浏览器／桌面窗口，确认所属进程退出且端口释放；刷新不关服，别的 CLI 分析继续。验证 Windows 安装器和 WebView2 启动，缺失组件显示可恢复错误。
- [x] **Step 5:** 提交 `feat: unify launch and shutdown across desktop browser and terminal`。

## Task 6: 科研迁移、定位文档与发行验收

**Files:**
- Modify: `README.md`, `README.zh-CN.md`, `PRODUCT.md`, `docs/{architecture,release,cli}.md`, `NOTICE.md`
- Modify: `.github/workflows/ci.yml`, `scripts/{verify_wheel,verify_source_install}.py`
- Create: `docs/research/{migration,limitations,performance}.md`, `docs/assets/research-validation.json`
- Test: `tests/research/test_research_install.py`, `web/tests/research-journey.spec.ts`

**Interfaces:**
- Consumes: 核心迁移报告、任务 1 性能记录、三个客户端安装入口。
- Produces: 首次使用说明、功能入口对照、矩阵与探针覆盖矩阵、默认预算与真实基准、成功／失败示例和可打开的离线报告。
- 产品工作名称使用 Scientific Dataflow Inspector；正式发行名／命令名在命名空间确认后确定。旧 `sfa`／`cdaf` 兼容表逐项列出，不擅自更改远端仓库名或发布 PyPI。

- [x] **Step 1:** 写干净环境无密钥体验、独立科研解释器接入、旧项目只读迁移、离线报告不泄漏敏感列、桌面／Web／CLI 完整旅程验收。
- [x] **Step 2:** 运行研究安装与旅程测试，确认文档／发行资源尚不满足新流程而失败；保留旧测试的状态说明。
- [x] **Step 3:** 重写定位与首页截图，打包新工作台／CLI／桌面入口，提供解释器选择与恢复说明；文档分别列出实现、限制与后续扩展。
- [x] **Step 4:** Python 服务与批处理安装在 Windows／macOS／Linux、Python 3.11–3.13 验证；桌面首版完成 Windows 安装和真实关闭验收，macOS／Linux 未完成的桌面验证明确标注。记录同机性能前后值及 10 分钟稳态开销；人工执行打开自有脚本→观察矩阵→找异常→配置探针→审查解释范围→关闭这一旅程。
- [x] **Step 5:** 提交 `docs: release the scientific dataflow workbench with verified installation paths`；按已有授权更新功能分支和草稿 PR，保留未验证项，未经授权不合并 master 或发布。

## 执行交接

按用户后续授权在当前主会话顺序实施；任务 1–6 已完成，十二项最终审查修复及完整本机／安装／原生关闭验收已通过；产品修复提交 110786c 的九环境 Python 和前端 CI 全部通过。产品代码、服务与发行变更均已有可运行实现，最终验证范围和技术裁决记录在发行审查中。
