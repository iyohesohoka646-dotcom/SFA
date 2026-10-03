# Scientific Dataflow Inspector · 科研数据流观察器

**可扩展探针、计算关系与智能代码审查的本地科研工作台。**

导入已有分析代码，配置呈现与检查探针，再明确执行计算和绘图。

[English](README.md) · [快速使用](docs/research/quickstart.md) · [交互 CLI](docs/research/cli.md) · [扩展协议](docs/research/adapter-api.md) · [发行验证](docs/release.md)

![真实运行的源码、矩阵、局部数据流与探针](docs/assets/research-workbench.png)

在同一界面查看变量在哪里定义、维度与类型是什么、运算怎样改变数据、异常首先在哪里出现。基础观察与规则解释不需要密钥。核心协议支持可扩展数据类型，NumPy／pandas 是首批内置适配器。

## 工作台 0.5

计算关系图提供函数、条件和循环底板、运算端口、结构／数据／执行视图，以及真实分支选择与循环计数。对象浏览器按块组织并支持共享多选。单击只选择，双击或右键菜单显式打开数据、源码；淡化无关对象默认关闭。标签和分屏可拖动、调整、缩小、放大、固定和保存。

探针按作用对象、呈现／检验／解释／推导用途和实现方式分类。探针库管理资源，探针台管理绑定；有效探针决定图形与表格，停用或删除不会复活。矩阵可定义数值、坐标、轴与单位，多对象可比较或生成带父输入引用的派生数据。公开绘图库、声明式自定义程序、Skill 和模型均保留独立接入接口。导入及配置不执行，运行、重绘和模型调用均由明确动作触发。Web 与 Windows 桌面内嵌真实 Python、Shell 和应用 CLI 终端。

智能助手自动构建环境、对象、工具、任务和预算上下文。用户配置模型与任务权限，实际发送内容、工具调用和引用可查看；源码和数据样例按范围读取。AI 可以生成函数体、稳定赋值或新分析文件提案，差异验证后仍须人工接受；接受后重新解析，计算仍需显式运行。[完整工作台说明](docs/research/workbench.md)

## 本地体验

Python 3.11–3.13，在项目目录安装：

```powershell
python -m pip install ".[research,views]"
cdaf studio --project .\experiment
```

选择示例，或填写自己的 `.py` 文件和计算解释器，先“导入解析”，配置探针，再点击“运行”。选择 `X`、`Z`、`C` 查看定义、形状、预览、表达式与上游。示例加入 `--failure nan` 后正常返回，但数值探针失败，可以直接追踪来源。

安装包包含构建后的 Web UI，普通使用不需要 Node.js 或密钥。也可直接安装功能分支，无需 Git：

```powershell
python -m pip install "contract-driven-ai-flow[research,views] @ https://github.com/iyohesohoka646-dotcom/SFA/archive/refs/heads/feat/contract-driven-ai-flow.zip"
cdaf studio --project .\experiment
```

关闭最后一个浏览器标签后，服务宽限 3 秒再停止，刷新不会关服。持续服务使用 `cdaf serve --project PATH`。Windows 桌面复用界面并携带私有 Python，关窗清理自己启动的服务。[本地部署](docs/local-deployment.md) · [桌面构建](desktop/README.md)。

## 三个入口与模型设置

| 入口 | 用途 |
| --- | --- |
| `cdaf studio --project PATH` | 源码、数据、局部运算、探针与时间线 |
| Windows 桌面 | 同一工作台，单实例、关窗清理，顶部打开终端 |
| `cdaf terminal --project PATH` 或终端里的 `cdaf` | `/open /run /vars /probe /model /explain /help` |
| `cdaf observe analysis.py --python PATH --project PATH` | 独立科研环境中的批处理观察 |
| `cdaf --json research runs --project PATH` | 自动化读取历史，不重新执行 |

采集代理以标准库为基础，科研库来自所选解释器。独立 CLI 分析有自己的进程所有权，可以在查看器关闭后继续。

**模型设置在顶部。** 默认离线规则。OpenAI-compatible／Anthropic 配置与 `/model`、`cdaf models` 共用项目存储，连接测试与推理测试分开。密钥保存为明确的环境变量或系统凭据库引用。智能任务自动读取环境和工具，可以查看实际调用记录；脱敏样例默认关闭，模型输出保留尚未人工验证的标记。

## 观察能力与扩展

原生数组、标量与表格覆盖复数、高维、空数组、缺失值和重复索引。观察版本包含源码摘要、形状、用户声明的轴／单位和精度。Canvas 预览、历史切片、虚拟化列表与脱敏离线报告展示已保存证据。执行与质量分开：程序完成仍可能探针失败。

矩阵预览最多 32×32，已保存数据切片最多 64×64。完整采集默认关闭，单产物通常限 64 MiB、单运行 256 MiB；未保存历史完整数据显示不可用。

| 扩展接口 | 职责 |
| --- | --- |
| `cdaf.research.adapters` | 描述并采集其他原生类型，声明真实能力 |
| `cdaf.research.probes` | 独立进程中的只读检查，明确范围与预算 |
| `cdaf.research.runners` | 其他执行后端输出同一事件协议 |
| 前端渲染器注册表 | 根据描述符与样例显示专用视图 |

插件须显式启用。[点云适配器](examples/research/custom-adapter.py)和[散点渲染器](web/src/research/PointCloudView.tsx)展示了不修改核心即可接入的独立类型。[扩展协议](docs/research/adapter-api.md) · [探针协议](docs/research/probe-api.md)。GPU、稀疏、分布式、延迟对象与非 Python 后端预留接口，当前尚未内置支持。

## 验证、限制与兼容

[性能记录](docs/research/performance.md)覆盖 1000 个逻辑变量／80 个可见节点／10000 条事件及两次十分钟真实 10 Hz 矩阵运行。只缓存历史元数据后，本机最后两分钟浏览器堆内存中位数由 59.08 降至 13.57 MiB。这些测量不构成通用开销上限或生产负载认证。

自动插桩有[明确覆盖边界](docs/research/instrumentation.md)，关系区分实际观察、源码推断与用户声明。代码和插件具有用户本身的文件／网络权限，见[限制](docs/research/limitations.md)。

产品工作名称为 Scientific Dataflow Inspector。发行包 `contract-driven-ai-flow`、导入 `contract_driven_ai_flow`、命令 `cdaf`、仓库 `SFA` 保持兼容。当前是 **0.5.1 本地候选版本**，没有更名远端或发布 PyPI；启动恢复与管理修复见[本次审查记录](docs/research/workbench-audit-0.5.1.md)。`sfa` 保留别名。契约工作流从“旧版架构”进入，见[旧工作流](docs/workflow.md)。[迁移](docs/research/migration.md)保留原文件和历史 ID，不补造矩阵证据。

## 设计与开发

Archify 的图形质量、Hamilton 的 Python 数据流、Codex／Kilo／DeepSeek Harness 的客户端事件与生命周期构成参考方向。[架构](docs/architecture.md) · [设计](docs/superpowers/specs/2026-10-01-scientific-dataflow-refactor-design.md) · [贡献](CONTRIBUTING.md) · [第三方说明](NOTICE.md)。

MIT，基于原始 SFA。[草稿 PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1)。
