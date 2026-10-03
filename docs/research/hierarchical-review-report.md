# 独立审查原始报告

审查范围：`11c6124fbe5bc157c182fc1d8774989a9f3a6f4f..26d23120ddd0c3e345e2703a0d6c986d65e0bbba`。一次新审查，审查者只读；下文保留原报告。修复和最终裁决见验收账本。

### Strengths

- 控制插桩保留原始条件与迭代器表达式；已有对照测试检查真值调用次数、短路、递归及 finally 覆盖跳转。累计摘要、512 条详情上限和最终收据也有清晰区分。
- 探针配置、资源、冻结调用与证据版本分离明确；默认探针删除持久化、完整产物校验和递归保护派生父产物的设计合理。
- Dockview、终端认证及生命周期均有实际实现。WebSocket 在处理终端内容前验证 Origin 和令牌，终端输出没有自动进入模型上下文。

审查基于 `26d2312`，未修改跟踪文件或运行浏览器/Electron。下面注明“复现”的问题均使用隔离临时目录；POSIX 用例在 WSL Ubuntu 中执行仓库实际 `_PosixPTY` 类，创建的测试进程已清理。

### Critical — Must Fix

**1. [P1] 函数控制摘要绕过源码脱敏。**
位置：`src/contract_driven_ai_flow/research/agent/instrument.py:188`。函数引用直接保存 `source_ref(node)` 的原始函数体，随后未经清洗进入 `control.summary` 和持久化控制表。已复现：函数包含合成 `api_key` 字符串时，数据快照正确标记 `binding:api_key` 已脱敏，但 `store.control_summaries()` 仍返回明文凭据。用户分享证据或查看控制结果时会泄漏本应隐藏的内容。应在函数控制引用进入传输前统一清洗源码，并测试持久化摘要、bootstrap 和相关导出均不含合成凭据；还应处理已经保存的受影响控制记录。

### Important — Should Fix

**2. [P1] 图和对象树生成的函数、操作选择身份与后端契约不一致。**
位置：`web/src/research/workspace/RelationGraph.tsx:271`、`web/src/research/workspace/selection.ts:143`、`src/contract_driven_ai_flow/research/workbench/scopes.py:10`。函数 UI 使用 `path::f::function@...`，后端使用 `path::<module>::f`；照 UI 构造选择后，`resolve_scope()` 已复现抛出 `Selected target is unavailable`。操作节点的 `logical_key` 则默认是空串，`??` 保留空串，导致多个操作共享 `selectionKey="operation:"`，也无法匹配后端的 `operation@line:column`。这破坏函数/操作选择、多选及“当前选择”运行。应共享规范的 TargetRef 构造规则，并覆盖函数、同一行多个操作、call、return 的前后端契约测试。

**3. [P2] 选择历史证据版本后，会静默完成零次探针调用。**
位置：`src/contract_driven_ai_flow/research/workbench/service.py:201`。UI 运行所选历史版本时只传 `target_scope`；此处默认读取 latest 快照，仅额外补入 joint 实例引用的版本，没有补入选择中的 `snapshot_id`。已复现 `X=1; X=2`，明确选择 v1 后得到 `resolved_targets=[]`、`invocations=[]`，任务最终 `completed` 且 `outputs=[]`。应加载并验证选择中的确切快照；失效的确切选择应明确报错，不能静默成为空作用域。

**4. [P1] 派生数据丢失坐标，后续联合运算可绕过坐标对齐检查。**
位置：`src/contract_driven_ai_flow/research/workbench/joint_worker.py:278`、`src/contract_driven_ai_flow/research/workbench/derivation.py:231`。派生快照和派生记录没有保存结果轴语义。已复现：分别对坐标 `[s1,s2]` 和 `[s2,s1]` 的两组输入进行合法逐元素派生，两份结果均 `semantics=None`；再次相加时返回 `ready/exact`，按位置产生 `[2211,1122]`，没有发现参与者顺序相反。应按运算传播结果坐标和来源，例如逐元素保留一致坐标、matmul 保留外轴、聚合移除被聚合轴；不能确定结果语义时须保留明确缺口并阻止默认坐标运算。

**5. [P2] 复用逻辑绑定的坐标没有按当前证据形状重新验证。**
位置：`src/contract_driven_ai_flow/research/workbench/service.py:247`、`src/contract_driven_ai_flow/research/workbench/joint_worker.py:102`。坐标只在用户保存语义时检查长度，计划冻结和实际运算只比较两边坐标是否相同。已复现：先给长度 2 的 A/B 保存两个坐标，再采集同名长度 3 的 A/B，联合计算仍返回 `ready`，没有坐标诊断。应对每个确切输入重新验证冻结语义与实际 shape，compute 模式应在新证据产生后验证；长度失配要阻止默认坐标计算。

**6. [P1] POSIX PTY 没有建立 controlling terminal，Ctrl+C 无效。**
位置：`src/contract_driven_ai_flow/research/workbench/terminal.py:97`。`openpty()` 后使用 `start_new_session=True` 并继承已经打开的 slave，并不会自动让它成为新会话的控制终端。实际 Ubuntu 用例中，子进程 `os.tcgetpgrp(0)` 返回 `ENOTTY(25)`；写入 `\x03` 只回显 `^C`，睡眠中的 Python 继续运行。应在子进程创建期间正确获得控制终端并设置前台进程组，并验证 Python 中断及交互 shell job control。

**7. [P1] POSIX 结束会话会遗留忽略 SIGTERM 的子进程。**
位置：`src/contract_driven_ai_flow/research/workbench/terminal.py:138`。关闭时向进程组发送 SIGTERM，但是否升级 SIGKILL 只取决于主进程的 `wait()`。主进程退出后，仍存活的后代不再清理。已复现：终端进程创建同组、忽略 SIGTERM 的子进程；`close()` 返回后，子进程仍为运行中的 `S` 状态。应独立确认并终止拥有的剩余进程，不能把 leader 退出视为整棵树退出；修复控制终端后还需覆盖 shell 创建独立前台进程组的情况。

**8. [P2] 被拆分的合法 UTF-8 输出会使 POSIX 会话提前结束。**
位置：`src/contract_driven_ai_flow/research/workbench/terminal.py:122`、`src/contract_driven_ai_flow/research/workbench/terminal.py:284`。增量解码器收到不完整字符时可以返回空字符串，`_drain()` 却将其视为 EOF 并结束会话。已复现分两次输出“中”的 UTF-8 字节：第一次 `read()` 返回 `""` 且进程仍活着，第二次才返回“中”。应区分原始字节 EOF 与解码器等待后续字节，并增加拆分 Unicode 输出测试。

**9. [P2] with 上下文表达式及绑定被静态图跳过，合法局部变量被误报未绑定。**
位置：`src/contract_driven_ai_flow/research/workbench/semantics.py:539`。with 分支直接分析 body，没有分析 `context_expr` 或创建 `optional_vars` 的定义。已复现 `with nullcontext(10) as x: y=x+1`：图没有上下文调用及其输出绑定，反而报告 `x may be read before local assignment`。这影响常见文件、锁和数据上下文代码的依赖解释。应建立上下文输入/调用、进入上下文后的绑定及对应源码对象，再分析 body。

**10. [P2] 全局快捷键仍会在普通输入框中触发工作台运行。**
位置：`web/src/research/ResearchWorkbench.tsx:464`。window 的 Ctrl/Cmd+Enter、Ctrl/Cmd+K 处理器没有检查输入元素、contenteditable 或 `defaultPrevented`。因此普通参数/问题输入框中使用这些键仍会启动计算或切换视图菜单。这是保留下来的旧行为，但与本次明确要求“输入和终端快捷键保持局部”冲突。应排除编辑区域并尊重已处理事件，添加输入聚焦时不会创建任务的浏览器测试。

### Minor

未发现值得单独提出的轻微问题；上述问题应优先处理。

### Recommendations

把上述触发器加入同一次 RED→GREEN 修复：选择身份与历史版本用前后端契约和实际交互检查；坐标问题用连续两级派生验证；脱敏检查持久化结果；POSIX 测试检查 controlling terminal、真实信号、后代退出和拆分 Unicode。之后执行既定整套测试与发布验证。

### Declined to judge

- 文件夹导入的完整产品行为：批准范围仅包括协议与开发样例。
- 跨文件计算图及执行：批准范围仅包括扩展契约。
- 重叠 computation stream 的完整 UI/执行：批准范围仅包括成员引用协议与样例。
- async 与 generator 的完整运行追踪：明确排除，本次仅检查其覆盖声明。
- 动态代码、动态/native 调用的完整静态求解：明确标记覆盖限制，未要求推断为完整关系。
- 当前版本在四种宽度、不同 zoom/DPI 下的 Dockview 实际效果：完成静态检查，但按审查约束未运行浏览器；由正在进行的实际效果验证裁定。
- 当前安装包的 Electron/ConPTY 生命周期和 Windows 原生外观：未启动或干扰正在进行的安装包验证。
- 隐藏图视图仍保持挂载的实际性能代价：读到了该实现，但未做浏览器性能测量，不能据此断言回归。
- 最终整套测试、最新提交的跨平台 CI 和发布证据完整性：这些门槛明确仍在执行，未当作已完成承诺。
- 所有第三方模型服务的实时响应质量：本次没有调用外部服务，也不以离线测试代替该验证。

### Assessment

**Ready to merge? No.**

存在已复现的凭据泄漏、派生坐标丢失后仍给出 exact 结果，以及核心选择和 POSIX 终端故障。修复这些问题并通过剩余发布门槛后再合并。
