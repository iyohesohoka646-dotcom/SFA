# SFA 开发路线图（智能体任务规划用）

**文档类型**：开发路线图  
**目标读者**：智能体（AI 执行者，用于分解任务与制定执行计划）  
**目标**：构建麻雀虽小、五脏俱全的开源原型  
**约束**：Python only、单机、串行执行、CLI 界面、文件存储  
**原则**：每个里程碑定义明确的**输入、输出、完成标准**，便于智能体自行拆解为可执行任务

---

## M1：项目骨架就位

**输入**：无（从零开始）  
**输出**：
- `sfa` CLI 入口脚本，使用 Typer 框架，所有后续命令的占位符已注册
- `sfa init` 命令可用：在目标目录生成完整 `.sfa/` 目录结构
- `sfa extract` 命令可用：读取 `sfa.yml` 中的 `source_dir`，使用 tree-sitter 解析 Python 文件，提取函数和类定义，输出 `.sfa/elements.json`
- `sfa.yml` 配置文件模板（含所有必要字段及默认值）

**完成标准**：
- 在空白目录执行 `sfa init` 后，`.sfa/` 目录结构与设计文档一致
- 对包含若干 Python 文件的项目执行 `sfa extract`，`elements.json` 正确列出所有函数和类，每条记录含名称、文件路径、行号、参数列表、返回类型注解（若有）

---

## M2：模块与拓扑定义

**输入**：M1 的 `.sfa/elements.json`  
**输出**：
- `sfa module add` 命令可用：交互式或参数式从元素列表中选择若干元素，创建模块，生成 `.sfa/modules/{name}/contract.json` 和 `summary.md`
- Contract 自动推断：基于元素参数/返回值类型注解生成 JSON Schema 骨架
- `sfa module remove` / `sfa module list` 命令可用
- `sfa pipe add <source> <target> [--visibility L2]` 命令可用，更新 `.sfa/pipeline.yml`
- `sfa pipe remove` / `sfa pipe list` 命令可用
- Composite Module 支持：`sfa group <ids>` 打包，`sfa ungroup <id>` 拆封，`sfa drill <id>` 切换上下文至内部视图

**完成标准**：
- 用户可从 `elements.json` 中选择元素创建模块，contract 自动生成且可手动编辑
- 管道在 `pipeline.yml` 中正确存储，系统校验源和目标模块存在
- 复合模块的 group/ungroup/drill 正确维护父子关系和内部子图

---

## M3：AI 生成闭环

**输入**：M2 的模块契约和管道定义  
**输出**：
- `sfa generate <module>` 命令可用
- 上下文组装逻辑：根据目标模块的 Input Contract 和管道可见性级别（L1-L4），组装发送给 LLM 的提示词
- LLM 调用层：支持 OpenAI 和 Anthropic，通过 `sfa.yml` 配置切换
- 后处理：静态扫描生成的代码中的 import 语句，对照白名单标记违规；检测全局副作用模式
- Diff 展示：生成 unified diff，在终端展示
- 用户交互：接受（应用 diff 写入文件，存入 history）或拒绝（丢弃）
- `sfa rollback <module>` 命令可用：列出历史版本，恢复指定版本

**完成标准**：
- 为模块生成代码时，AI 仅看到该模块的契约和按可见性级别提供的上游信息
- 生成的代码以 diff 形式展示，用户接受后才写入
- 白名单外的 import 被标记警告
- 回滚可恢复到任意历史版本

---

## M4：执行与快照闭环

**输入**：M3 的模块代码 + 拓扑定义  
**输出**：
- `sfa run` 命令可用
- 拓扑排序：读取 `pipeline.yml`，生成模块执行序列
- 执行引擎：按序列加载并执行每个模块
- 契约校验：每个模块执行前，用 jsonschema 校验输入是否符合 Input Contract（校验级别依模块配置：strict/lenient/none）
- 遇错即停：异常时输出模块名、输入快照路径、错误堆栈
- 快照引擎：每个模块执行后，将输入/输出/耗时/状态写入 `.sfa/snapshots/{run_id}/{module}.json`，并记录 contract_version_hash
- `sfa observe` 命令可用：列出本次或最近一次运行的模块摘要（状态灯、输入/输出简述、耗时）
- `sfa observe <module>`：查看指定模块的详细快照

**完成标准**：
- 一条命令即可执行完整管道，无需人工逐步调用
- 每个模块的输入/输出自动记录为结构化快照
- 契约校验在管道边界自动生效，不依赖模块内部代码
- 观察视图可快速定位异常模块，无需阅读代码或调用 AI

---

## M5：探针系统

**输入**：M4 的管道和快照基础设施  
**输出**：
- `sfa probe add router` 命令可用：创建路由探针，附着在指定管道上，定义条件表达式、on_true 和 on_false 分支
- `sfa probe add assertion` 命令可用：创建断言探针，定义行为断言表达式
- 探针 DSL 解析器：支持 `$output.field` 语法，静态校验字段存在于上游 Output Schema
- 探针执行：路由探针根据条件结果将数据导向不同分支；断言探针失败时抛出 `ProbeEvaluationError`，附上下文
- `sfa probe list` / `sfa probe remove` 命令可用

**完成标准**：
- 条件路由不污染模块代码，路由规则定义在探针节点中
- 断言探针失败时输出明确的期望与实际值对比
- 探针表达式在定义时进行静态校验，路径错误当场报错

---

## M6：可视化、索引与开源发布

**输入**：M1-M5 全部功能  
**输出**：
- `sfa list` 命令可用：以表格形式展示所有模块，含名称、类型（Atomic/Composite）、最近运行状态灯、输入/输出一行简述
- `sfa graph <module>` 命令可用：以 ASCII 文本图展示指定模块的上下游邻域子图（1-2 跳）
- `sfa graph`（无参数）：展示顶层完整数据流文本图；节点数超过阈值时自动折叠为索引视图
- 附带示例项目：`examples/` 目录下至少一个完整 Demo（如数据处理流水线），含模块定义、管道、探针、运行快照
- README.md：项目介绍、安装方式、快速开始教程、命令参考
- CONTRIBUTING.md：贡献指南
- LICENSE 文件

**完成标准**：
- 示例项目可一键运行（`sfa init` + `sfa run`），产出可观测快照
- README 教程覆盖从零到完整运行的完整流程
- 项目可在 GitHub 上直接克隆、安装、运行，无额外隐藏依赖

---

## 全局约束（所有里程碑适用）

- 所有 `.sfa/` 下的存储文件为人类可读的 JSON/YAML/Markdown
- 错误信息始终包含：出错的模块名、相关文件路径、可操作的建议
- CLI 命令遵循一致命名模式：`sfa <noun> <verb>` 或 `sfa <verb> <noun>`
- 每个里程碑完成后，其功能通过手动跑通示例项目来验收