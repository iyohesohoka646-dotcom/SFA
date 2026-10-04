# Scientific Dataflow Inspector 0.5.4 本地候选版

0.5.4 恢复 Code 图中的计算依赖和条件连接，使用圆形判断与菱形运算、换行标签和连续分层排线；修复块拖动、源码范围高亮及运行信息重叠。探针台改为三种操作模式，探针库新增组合模板，数据页严格按有效绑定呈现。通用模型服务从空白配置开始，预设可选。[本轮改进与验证](research/process-probes-0.5.4.md)。

0.5.3 简化为逻辑变量表与 Code／Data 两种关系图，每个启用的呈现探针对应独立可折叠视图。修复下拉选择、重复变量历史、保存后立即执行的版本冲突、异步任务抢占放大视图、数值表坐标和嵌套循环纵向布局。网格、统一单元尺寸、正交排线与 Back／Root 提供紧凑导航。[本轮改进与验证](research/compact-workbench-0.5.3.md)。

0.5.2 按截图反馈更新对象浏览器、探针绑定、模型选择和计算图：重复赋值按词法作用域合并并显示最后实际观测值，选中后标出同作用域内全部源码引用；探针台分对象列出已有绑定，探针库保存新实例的默认参数；图设置浮在画布上，结构、数据和执行视图区分语义，支持拖动画布、标记折叠端口及嵌套布局。智能助手增加书写整理提案，在语法树、注释和编码校验后供用户审查。[本轮改进与验证](research/interaction-refinement-0.5.2.md)。

0.5.1 修复启动恢复、单视图错误隔离、后台分屏加载丢失点击和焦点、终端隐藏状态、探针筛选与重复绑定、旧版计算图迁移、历史源码选择、自定义模板、历史结果查询及展平相关运算的代码提案。桌面“退出并停止”会结束应用及其所属服务；“设置 → 版本信息”显示实际软件版本。[本次审查与验证](research/workbench-audit-0.5.1.md) 单独记录安装入口、迁移和回归证据。

0.5 将研究范围、探针和运行证据连成完整工作台：对象树与分层计算图共享选择；函数、条件和循环用可折叠底板表达；呈现、检验、解释和推导探针分别绑定到明确目标；多对象可以并排比较、计算派生数据并追溯输入。Web、Windows 桌面和 CLI 使用同一套服务。发行包继续使用 `contract-driven-ai-flow`，导入名和旧架构入口保留。[草稿 PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1) 用于审查，尚未合并 master 或发布 PyPI。

## 操作

选择 Python 脚本后点击“导入解析”；这一步不运行用户代码。单击对象或图节点只选择，Ctrl/Cmd 和 Shift 支持多选；双击、Enter 或右键菜单才打开数据、源码或进入块。关系图默认为 Code，Data 只显示变量依赖。保留完整背景，淡化可单独开启；Arrange 使用 ELK Worker 的对齐与正交排线，选择、数值更新和淡化不重新布局。每个有效呈现探针有独立可折叠区域，可以设置或固定为独立标签。

新项目应用可管理的“自动数据视图”探针模板；成员按数据类型提供基础呈现，没有有效探针时仅保留变量名和探针台入口。表格、热图和其他图形由有效呈现探针提供。探针库分别管理公开资源、已安装扩展、自定义程序和 Skill；参数修改先保存绑定，计算、绘图和模型调用都需要明确点击执行。联合计算需要完整输入，缺少完整数据或坐标会给出诊断，补采集产生新运行。

“设置”管理工作区、关系图、默认探针、采集、智能模型、扩展环境、终端和存储。模型设置保留顶部直接入口。Dockview 支持横纵分屏、标签拖动、缩小恢复、放大还原、命名布局和锁定。任务、结果和事件按运行、阶段、目标与探针筛选。内嵌终端支持 Python、应用 CLI 和系统 Shell；隐藏保留进程，显式结束或关闭拥有服务的应用时清理进程。

```powershell
python -m pip install "contract-driven-ai-flow[research,tables,views] @ https://github.com/iyohesohoka646-dotcom/SFA/archive/refs/heads/feat/contract-driven-ai-flow.zip"
cdaf studio --project .\experiment
cdaf terminal --project .\experiment
cdaf workbench --help
```

Windows 本地程序为 `dist/desktop/win-unpacked/Scientific Dataflow Inspector.exe`；NSIS 安装包为 `dist/desktop/Scientific Dataflow Inspector Setup 0.5.4.exe`。关闭最后一个拥有服务的浏览器标签后服务停止，刷新有宽限；需要持续服务时使用 `cdaf serve`。[工作台使用](research/workbench.md) · [CLI](research/cli.md) · [桌面构建](../desktop/README.md)。

## 验证与边界

0.5.4 的[机器可读验收记录](assets/workbench-process-validation.json)核对 783 项 Python 检查及 8 项平台条件跳过、111 项前端单元检查。92 个浏览器场景通过全套首轮和失败项修复复测核对；最后变更的 5 个交互场景另行全部通过，涵盖文件范围模板展开、关闭所有呈现后空白、块拖动与源码高亮、证据布局和通用服务配置。实际桌面、包安装及原项目保留情况分别记入同一记录，避免与静态构建检查混用。千对象选择 P95 为 5.2 ms，隐藏图时为 5.3 ms；此测量仅覆盖夹具中的选中到下一帧。

0.5.3 的[机器可读验收记录](assets/workbench-compact-validation.json)核对 87 个浏览器场景、103 个前端单元检查、773 项 Python 检查及 8 个平台条件跳过。Python 首轮唯一失败是本地 editable 安装元数据仍为 0.5.2，刷新安装后该项补测通过。原桌面快捷方式实际打开 0.5.3，原 3 次运行和数据库记录保留；248 个核心包文件与经过隔离安装检查的 wheel 逐字节一致。Windows 125% 原生使用和 150% 三种真实终端、重连、启动恢复与退出清理通过。类型与生产构建、wheel 和源归档隔离安装均通过。当前千对象选择 P95 为 6.1 ms，隐藏图时为 6.2 ms。[详细结果](research/compact-workbench-0.5.3.md)。

0.5.0 的检查、包摘要和审查裁决记录在[此前验收记录](research/hierarchical-workbench-validation.md)，0.5.1、0.5.2 保留原记录。测试区分结构解析、真实计算、浏览器操作、隔离安装和原生程序；性能记录注明夹具与测量范围。Windows 原生使用检查涵盖中文脚本、矩阵异常、配置绘图后重绘、共享 CLI 历史、内嵌多会话终端及关窗后的端口和进程释放。

[选择性能](assets/scientific-performance.json) 使用 1000 个对象、10000 条历史事件的夹具，检查选中样式实际变化并测量到下一帧的延迟；它不包含科学计算或冷导入。[解析性能](assets/scientific-parser-performance.json) 单独记录千级中文对象的静态解析。[运行开销](research/performance.md) 保留原有实验条件，不能推广成任意程序的速度保证。

本轮完成单个 Python 文件的分层计算语义与常见同步控制采集。文件夹、跨文件和用户圈定支流提供协议与开发示例；异步、生成器和动态代码保留结构及覆盖标记。程序探针和扩展使用所选解释器的文件与网络权限。默认摘要采集，完整数据和外部模型调用需要明确配置；工作台内的真实远程模型推理未在本轮调用，验证的是离线模式与 HTTP 工具循环夹具。

Windows 包为未签名本地候选。打包程序和 NSIS 构建、安装向导、macOS/Linux 原生桌面验收分别记录，不能互相代替。跨平台 CI 以该分支最新提交的 GitHub Actions 状态为准。[扩展协议](research/adapter-api.md) · [探针协议](research/probe-api.md) · [迁移说明](research/migration.md) · [覆盖限制](research/limitations.md)。
