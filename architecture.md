# SFA 系统架构设计文档

**文档类型**：系统架构设计  
**目标读者**：智能体（AI 执行者）  
**语言**：中文  
**对应阶段**：Phase 0 MVP 及后续扩展的架构基座  

---

## 1. 核心领域模型

### 1.1 实体定义

| 实体 | 定义 | 核心属性 |
|------|------|----------|
| **Project** | 一个 SFA 项目 | name, language, source_dir, AI 配置, 默认可见性级别, 库白名单, 校验严格度 |
| **Module** | 语义模块，可递归 | id, name, type(Atomic/Composite), path(代码文件), input_contract, output_contract, summary, visibility_override, validation_level |
| **Pipe** | 模块间的数据管道 | id, source_module_id, target_module_id, visibility(L1-L4) |
| **Contract** | 模块的输入/输出接口定义 | module_id, direction(input/output), schema(JSON Schema), natural_summary, version_hash |
| **Snapshot** | 单次运行中模块边界的实际数据 | run_id, module_id, direction(input/output), data(脱敏后), timestamp, execution_time_ms, status(success/fail), contract_version_hash |
| **Probe** | 附着在管道上的探针 | id, pipe_id, type(router/assertion), condition_expression, on_true(router), on_false(router) |
| **Run** | 一次执行会话 | run_id, start_time, end_time, overall_status |

### 1.2 模块层级模型

- **Atomic Module**：叶子模块，包含实际的源代码文件
- **Composite Module**：容器模块，内部包含子模块和子管道的子图
- 复合模块对外暴露聚合后的 Input/Output Contract（由其内部子图拓扑计算得出）
- 操作：
  - `group(module_ids)` → 打包为新 Composite Module
  - `ungroup(composite_module_id)` → 拆封，将子模块提升至当前层级
  - `drill(composite_module_id)` → 进入内部视图

## 2. 系统分层架构

```
┌─────────────────────────────────────┐
│         用户界面层                    │
│  CLI (Typer)        │  Web UI (未来) │
│  命令路由与参数解析  │  REST API      │
├─────────────────────────────────────┤
│         核心引擎层                    │
│  ┌───────────┐ ┌──────────┐ ┌──────┐│
│  │ 拓扑引擎  │ │ 执行引擎  │ │快照引擎││
│  │ 节点/管道 │ │ 拓扑排序  │ │ 记录  ││
│  │ CRUD      │ │ 调度执行  │ │ 快照  ││
│  └───────────┘ └──────────┘ └──────┘│
│  ┌───────────┐ ┌──────────┐ ┌──────┐│
│  │ 契约引擎  │ │ 探针引擎  │ │ AI层 ││
│  │ Schema校验│ │ 条件路由  │ │上下文││
│  │ 版本比对  │ │ 静态检查  │ │组装  ││
│  └───────────┘ └──────────┘ └──────┘│
├─────────────────────────────────────┤
│         存储层                       │
│  文件系统 (.sfa/)                    │
│  JSON / YAML 读写                    │
├─────────────────────────────────────┤
│       语言解析层                     │
│  Tree-sitter Python                 │
│  提取函数/类/参数                    │
└─────────────────────────────────────┘
```

## 3. 核心模块详细设计

### 3.1 拓扑引擎

- 职责：管理 `pipeline.yml` 中的模块节点和管道定义
- 功能：
  - 节点 CRUD：添加、删除、重命名模块，移动模块到 Composite
  - 管道 CRUD：建立/删除模块间管道，修改可见性级别
  - 有效性校验：检查管道两端模块存在性，检查无循环依赖（对 DAG）
  - 查询：获取某模块的上下游依赖图（邻域子图）
  - 复合模块管理：group/ungroup/drill 操作，维护内部子图

### 3.2 契约引擎

- 职责：管理每个模块的 Input/Output Contract
- 功能：
  - 从代码文件自动推断 Schema（基于 AST 分析参数和返回类型注释）
  - 允许用户手动编辑 Schema 和自然语言摘要
  - 版本化：每次 Schema 变更生成 version_hash（内容 SHA256）
  - 校验：运行时在管道边界对数据执行 JSON Schema 校验
  - 兼容性检查：对比上游输出 Schema 版本与下游生成时记录的期望版本，不匹配时发警告
- 存储：`.sfa/modules/{module_name}/contract.json` + `summary.md`

### 3.3 执行引擎

- 职责：按拓扑顺序调度模块执行，记录快照
- 执行流程：
  1. 读取 `pipeline.yml`，拓扑排序得到执行序列
  2. 对每个模块：
     a. 契约校验：检查输入数据是否符合模块 Input Contract（校验级别依模块设置）
     b. 执行模块代码（加载模块文件，调用入口函数）
     c. 捕获输出和异常
     d. 快照引擎记录输入/输出/耗时/状态
  3. 遇错即停（Fail-Fast）：抛出异常，包含模块名、输入快照路径、错误堆栈
- 后续扩展：并发执行 + 资源声明冲突检测

### 3.4 快照引擎

- 职责：将每次模块执行的实际数据持久化
- 存储结构：`.sfa/snapshots/{run_id}/{module_name}.json`
- 快照内容：
  ```json
  {
    "module": "module_name",
    "run_id": "uuid",
    "timestamp": "ISO8601",
    "duration_ms": 123,
    "status": "success" | "error",
    "input": { ... },
    "output": { ... },
    "error": "traceback if failed",
    "contract_version": "input_schema_hash"
  }
  ```
- 脱敏：根据 `sfa.yml` 中的 `sensitive_fields` 模式，在写入前替换匹配字段为 `***REDACTED***`（Phase 1 实现，MVP 仅记录并警告）

### 3.5 AI 代理层

- 职责：与 LLM 交互，生成模块实现代码
- 上下文组装规则：
  - 仅包含目标模块的 Input/Output Contract 及其自然语言摘要
  - 根据管道的可见性级别包含上游模块信息：
    - L1：仅上游 Output Schema
    - L2（默认）：上游 Output Schema + 3-5 组输入输出样例（从快照中选取）
    - L3：L2 + 上游代码结构摘要（函数列表）
    - L4：上游全部源代码
  - 不包含下游模块的任何信息
- 生成后处理：
  1. 静态扫描 import 语句，对照 `allowed_imports` 白名单标记违规
  2. 检测全局副作用模式（`os.environ` 修改等），标记警告
  3. 生成 unified diff 文件，不在原文件直接写入
- 安全约束：
  - 提示词中注入约束：“只能使用以下库：xxx。如需其他库，先以注释说明理由并请求批准。”
  - 用户审查 diff 后手动接受/拒绝

### 3.6 探针引擎（Phase 1）

- 职责：提供不改变数据流的路由和断言功能
- 探针类型：
  - Router：附着在管道上，根据条件表达式将数据路由到不同分支（on_true/on_false）
  - Assertion：在管道点做行为断言（如 `$output[0] <= $output[-1]`），断言失败报警
- 表达式语言：受限 DSL，如 `$output.field > 0.8`，静态检查字段是否存在于上游 Schema 中
- 运行时求值失败则抛出 `ProbeEvaluationError`

## 4. 数据存储规范

### 4.1 `.sfa/` 目录结构

```
# 项目配置文件 sfa.yml 位于项目根目录（不在 .sfa/ 内）
.sfa/
├── pipeline.yml               # 拓扑定义
├── elements.json              # 代码元素提取缓存
├── modules/
│   └── {module_name}/
│       ├── contract.json      # 输入/输出 Schema
│       └── summary.md         # 自然语言描述
├── history/
│   └── {module_name}/
│       └── v{timestamp}.py    # 代码历史版本
├── snapshots/
│   └── {run_id}/
│       └── {module_name}.json
└── probes/                    # 探针定义（Phase 1）
    └── {probe_name}.yml
```

### 4.2 `pipeline.yml` 格式

```yaml
modules:
  - id: module_a
    name: 数据预处理
    type: atomic
    path: src/preprocess.py
    input_contract: .sfa/modules/module_a/contract.json
    output_contract: .sfa/modules/module_a/contract.json
    validation: strict

  - id: module_b
    name: 模型推理
    type: atomic
    path: src/inference.py
    input_contract: .sfa/modules/module_b/contract.json
    output_contract: .sfa/modules/module_b/contract.json

pipes:
  - id: pipe_a_b
    source: module_a
    target: module_b
    visibility: L2
```

### 4.3 Contract JSON 格式

```json
{
  "module": "module_b",
  "version_hash": "a3f2b1c9...",
  "input_schema": {
    "type": "object",
    "properties": {
      "user_id": {"type": "integer"},
      "features": {"type": "array", "items": {"type": "number"}}
    },
    "required": ["user_id", "features"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "prediction": {"type": "number"},
      "confidence": {"type": "number"}
    }
  },
  "natural_summary": "输入用户ID和特征数组，输出预测值和置信度"
}
```

## 5. 关键流程

### 5.1 定义模块

1. 用户执行 `sfa extract`，Tree-sitter 扫描 `source_dir` 生成候选元素列表
2. 用户执行 `sfa module add`，从元素中选择若干组合为模块，指定名称
3. 系统自动推断 Input/Output Schema（基于函数签名），存储至 `.sfa/modules/{name}/contract.json`
4. 用户可手动编辑 contract 和 summary

### 5.2 连接管道

1. 用户执行 `sfa pipe add <source> <target> [--visibility L2]`
2. 系统写入 `pipeline.yml`，校验源和目标模块存在

### 5.3 生成代码

1. 用户执行 `sfa generate <module>`
2. AI 代理层组装上下文（契约 + 按可见性级别的上游信息），调用 LLM
3. 后处理扫描，生成 diff 展示
4. 用户接受：应用 diff，存入 history；拒绝：丢弃

### 5.4 运行与调试

1. 用户执行 `sfa run`
2. 执行引擎拓扑排序，顺序执行模块
3. 每模块执行前后：契约校验 → 执行 → 快照记录
4. 出错时停止，输出具体上下文
5. 用户执行 `sfa observe` 查看模块摘要列表，点击模块查看快照详情

## 6. 技术选型

| 组件 | MVP 选型 | 备注 |
|------|----------|------|
| 运行时语言 | Python 3.11+ | 与目标代码同语言，便于动态加载模块 |
| CLI 框架 | Typer | 基于类型提示的 CLI，自动生成帮助 |
| AST 解析 | tree-sitter + tree-sitter-python | 精确提取函数/类定义 |
| Schema 校验 | jsonschema | JSON Schema 标准校验 |
| LLM 接口 | OpenAI SDK / Anthropic SDK | 可配置 |
| Diff 生成 | Python difflib | 生成 unified diff 文本 |
| 存储 | 文件系统 + PyYAML | 无需数据库，降低依赖 |
| 日志 | Python logging | 输出到 stderr 和 .sfa/logs/ |

## 7. 非功能性约束

- **安全**：AI 生成代码在人工确认前不写入文件系统；库白名单机制限制依赖
- **性能**：拓扑排序和契约校验应在毫秒级完成；快照写入异步化避免阻塞执行
- **可扩展**：探针系统使用插件化设计；多语言支持通过 Tree-sitter 语言包扩展
- **数据隐私**：快照存储可配置脱敏规则；建议 `.sfa/` 加入 `.gitignore`