# Scientific Dataflow Inspector 0.5.0 本地候选版

0.5 将研究范围、探针和运行证据连成完整工作台：对象树与分层计算图共享选择；函数、条件和循环用可折叠底板表达；呈现、检验、解释和推导探针分别绑定到明确目标；多对象可以并排比较、计算派生数据并追溯输入。Web、Windows 桌面和 CLI 使用同一套服务。发行包继续使用 `contract-driven-ai-flow`，导入名和旧架构入口保留。[草稿 PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1) 用于审查，尚未合并 master 或发布 PyPI。

## 操作

选择 Python 脚本后点击“导入解析”；这一步不运行用户代码。单击对象或图节点只选择，Ctrl/Cmd 和 Shift 支持多选；双击、Enter 或右键菜单才打开数据、源码或进入块。关系图默认为结构总览，保留完整背景；“淡化无关对象”可单独开启。首次导入和结构变化使用 ELK Worker 布局，选择、数值更新和虚化不重新布局。

新项目提供可见、可停用和可删除的“自动数据视图”探针。对象名称、类型、形状和来源始终可见，表格、热图和其他图形由有效呈现探针提供。探针库分别管理公开资源、已安装扩展、自定义程序和 Skill；参数修改先保存绑定，计算、绘图和模型调用都需要明确点击执行。联合计算需要完整输入，缺少完整数据或坐标会给出诊断，补采集产生新运行。

“设置”管理工作区、关系图、默认探针、采集、智能模型、扩展环境、终端和存储。模型设置保留顶部直接入口。Dockview 支持横纵分屏、标签拖动、缩小恢复、放大还原、命名布局和锁定。任务、结果和事件按运行、阶段、目标与探针筛选。内嵌终端支持 Python、应用 CLI 和系统 Shell；隐藏保留进程，显式结束或关闭拥有服务的应用时清理进程。

```powershell
python -m pip install "contract-driven-ai-flow[research,tables,views] @ https://github.com/iyohesohoka646-dotcom/SFA/archive/refs/heads/feat/contract-driven-ai-flow.zip"
cdaf studio --project .\experiment
cdaf terminal --project .\experiment
cdaf workbench --help
```

Windows 本地程序为 `dist/desktop/win-unpacked/Scientific Dataflow Inspector.exe`；NSIS 安装包为 `dist/desktop/Scientific Dataflow Inspector Setup 0.5.0.exe`。关闭最后一个拥有服务的浏览器标签后服务停止，刷新有宽限；需要持续服务时使用 `cdaf serve`。[工作台使用](research/workbench.md) · [CLI](research/cli.md) · [桌面构建](../desktop/README.md)。

## 验证与边界

本轮最终检查、包摘要、原生回执和审查裁决统一记录在[验收记录](research/hierarchical-workbench-validation.md)。测试区分结构解析、真实计算、浏览器操作、隔离安装和原生程序；性能记录注明夹具与测量范围。真实 Windows 桌面验收包含中文脚本、矩阵异常、配置绘图后重绘、共享 CLI 历史、内嵌多会话终端及关窗后的端口和进程释放。

[选择性能](assets/scientific-performance.json) 使用 1000 个对象、10000 条历史事件的夹具，检查选中样式实际变化并测量到下一帧的延迟；它不包含科学计算或冷导入。[解析性能](assets/scientific-parser-performance.json) 单独记录千级中文对象的静态解析。[运行开销](research/performance.md) 保留原有实验条件，不能推广成任意程序的速度保证。

本轮完成单个 Python 文件的分层计算语义与常见同步控制采集。文件夹、跨文件和用户圈定支流提供协议与开发示例；异步、生成器和动态代码保留结构及覆盖标记。程序探针和扩展使用所选解释器的文件与网络权限。默认摘要采集，完整数据和外部模型调用需要明确配置；真实远程模型推理未在本轮调用，验证的是离线模式与 HTTP 工具循环夹具。

Windows 包为未签名本地候选。打包程序和 NSIS 构建、安装向导、macOS/Linux 原生桌面验收分别记录，不能互相代替。跨平台 CI 以该分支最新提交的 GitHub Actions 状态为准。[扩展协议](research/adapter-api.md) · [探针协议](research/probe-api.md) · [迁移说明](research/migration.md) · [覆盖限制](research/limitations.md)。
