# Scientific Dataflow Inspector 0.4.0 本地候选版

0.4 提供统一探针工作台：独立标签与横纵分屏、视图缩小/全屏/关闭、命名与固定布局、版本并排、直接计算关系高亮、公开绘图库管理、自动智能任务 harness 和人工审查的代码提案。Web、Windows 桌面、交互终端和批处理 CLI 共用服务。发行名和旧架构入口保留，远端仓库仍为 SFA。[草稿 PR #1](https://github.com/iyohesohoka646-dotcom/SFA/pull/1) 承载审查，没有合并 master 或发布 PyPI。

## 验证

本轮完整 Python 检查 **573 passed**；前端单元测试 **20 passed**；完整真实浏览器检查 **45 passed**。浏览器旅程包含无执行解析、配置后计算、真实绘图和只重绘、矩阵图例与异常、复数/高维/表格/自定义点云、固定版本与历史图、布局恢复、窄屏、暂停后继续、过期响应、慢模型取消、自动工具循环和局部代码提案接受。CLI 与 HTTP 使用同一服务。

[本轮性能数据](assets/scientific-performance.json) 来自 1000 个变量、10000 条事件的有界夹具，最新点击到绘制 P95 **5.8 ms**、数据详情 P95 **6.9 ms**。这验证当前界面夹具；科研采集开销的历史实测、CPU 矩阵计算与十分钟采集在[性能说明](research/performance.md)中分别记录，不构成任意环境的速度保证。

全新 wheel 与 source 安装检查执行真实计算、四个绘图库、离线报告与模型 HTTP 工具循环夹具。当前 wheel 与项目内独立 Python 的 **221 个包文件**已逐字节核对。桌面运行时会强制重装同版本候选包后检查全部资源，避免元数据版本相同但实际代码陈旧。最终原生回执与安装包摘要见本轮发行记录。

[Windows 原生回执](assets/research-desktop-validation.json)已通过：运行中文脚本、矩阵异常与色带、配置绘图后只重绘、自动上下文、CLI 共用历史、报告脱敏、实际关窗与端口释放。[发行回执](assets/scientific-release-validation.json)记录本轮包摘要与文件核对。此原生检查运行的是打包目录中的程序，NSIS 安装向导本轮未执行；安装包已构建，仍为未签名本地候选。

矩阵默认使用显示单元的最小值到最大值线性色阶，提供数值色带、恒定值标识、缺失/NaN/Inf 纹理和原始行列索引；统计与采集细节可折叠。关系图点击显示直接输入、直接下游及来源，视图位置独立于执行语义。

## 使用

```powershell
python -m pip install "contract-driven-ai-flow[research,views] @ https://github.com/iyohesohoka646-dotcom/SFA/archive/refs/heads/feat/contract-driven-ai-flow.zip"
cdaf studio --project .\experiment
cdaf terminal --project .\experiment
cdaf research --help
```

顶部文件菜单选择脚本并“导入解析”，配置探针后“运行”。绘图库也可以在工具库安装到项目管理环境，计算环境单独选择。关闭最后一个拥有的浏览器标签后服务停止，刷新有宽限；持续服务用 `cdaf serve`。Windows 可运行 `dist/desktop/win-unpacked/Scientific Dataflow Inspector.exe`，或使用同目录 NSIS 安装包。[完整使用](research/workbench.md) · [CLI](research/cli.md) · [桌面构建](../desktop/README.md)。

## 已知范围

Python 本地工作台、NumPy/pandas/标准标量及独立点云适配路径已验证；GPU、稀疏、分布式和其他语言的内置后端尚未提供。Bokeh/PyVista/HoloViews 是公开候选，当前四个实际绘图适配器是 Matplotlib、Seaborn、Plotly、Altair。关系图区分观察和推断，任意拖线编辑程序语义尚未实现。反向代码支持函数体、稳定赋值和项目内新分析文件；结构有效仍标记行为未验证，回滚只支持可保真保存的局部片段。

程序和插件具有所选解释器的文件/网络权限。数据与源码脱敏发生在证据、浏览器、报告和模型上下文边界，完整采集默认关闭。远程真实模型推理没有在本轮调用；已验证的是离线模式与实际 HTTP 结构化工具循环夹具。Windows 原生包为未签名本地候选，macOS/Linux 原生桌面包未验证，跨平台 CI 结果以 GitHub 最新运行状态为准。[扩展协议](research/adapter-api.md) · [探针协议](research/probe-api.md) · [覆盖限制](research/limitations.md)。
